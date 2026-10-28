from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.enums import IntentType, RiskLevel
from app.schemas.dtos import AiMessage
from app.services.prompt_builder import AgentPromptBuilder, PromptBuildContext
from app.services.skills import MindBridgeSkill, MindBridgeSkillLibrary
from app.services.token_budget import TextBudgetCounter


@dataclass(frozen=True)
class ContextBudgetUsage:
    mode: str
    unit: str
    limit: int
    used: int
    history_chars: int
    memory_chars: int
    knowledge_chars: int
    skill_chars: int
    truncated_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuiltAgentContext:
    messages: list[AiMessage]
    selected_skills: list[MindBridgeSkill] = field(default_factory=list)
    budget: ContextBudgetUsage | None = None


class AgentContextBuilder:
    """Assemble bounded response context from memory, retrieval, Skills and runtime state."""

    def __init__(self, settings: Settings, prompt_builder: AgentPromptBuilder | None = None):
        self.settings = settings
        self.prompt_builder = prompt_builder or AgentPromptBuilder()
        self.budget_counter = TextBudgetCounter(settings.context_budget_mode)

    def build_response(
        self,
        *,
        intent: IntentType,
        risk: RiskLevel,
        display_name: str,
        user_input: str,
        skill_input: str | None = None,
        recent_history: list[AiMessage],
        memory_brief: str,
        retrieved_knowledge: list,
        knowledge_query: str = "",
        tool_context: str = "",
        planner_state: str = "",
        response_agent: str = "",
        response_plan: str = "",
    ) -> BuiltAgentContext:
        selected_skills = MindBridgeSkillLibrary.response_skills(intent, risk, skill_input or user_input)
        raw_skill = "\n\n".join(skill.prompt_context() for skill in selected_skills)
        raw_knowledge = "\n\n".join(
            _format_knowledge_evidence(index, item)
            for index, item in enumerate(retrieved_knowledge, start=1)
        )
        token_mode = self.settings.context_budget_mode.strip().lower() not in {"char", "chars", "character"}
        total_limit = max(1000, self.settings.context_max_tokens if token_mode else self.settings.context_max_chars)
        history_limit = self.settings.context_history_max_tokens if token_mode else self.settings.context_history_max_chars
        memory_limit = self.settings.context_memory_max_tokens if token_mode else self.settings.context_memory_max_chars
        knowledge_limit = self.settings.context_knowledge_max_tokens if token_mode else self.settings.context_knowledge_max_chars
        skill_limit = self.settings.context_skill_max_tokens if token_mode else self.settings.context_skill_max_chars
        remaining = max(0, total_limit - self.budget_counter.count(user_input))
        truncated = []

        skill_context, remaining = self._take(
            raw_skill,
            min(skill_limit, remaining),
            remaining,
            "skill",
            truncated,
        )
        knowledge_context, remaining = self._take(
            raw_knowledge,
            min(knowledge_limit, remaining),
            remaining,
            "knowledge",
            truncated,
        )
        bounded_memory, remaining = self._take(
            memory_brief,
            min(memory_limit, remaining),
            remaining,
            "memory",
            truncated,
        )
        bounded_history = self._fit_history(
            recent_history,
            min(history_limit, remaining),
        )
        history_chars = sum(self.budget_counter.count(item.content) for item in bounded_history)
        if history_chars < sum(self.budget_counter.count(item.content) for item in recent_history):
            truncated.append("history")

        prompt_context = PromptBuildContext(
            intent=intent,
            risk=risk,
            display_name=display_name,
            user_input=user_input,
            recent_history=bounded_history,
            memory_brief=bounded_memory,
            knowledge_context=knowledge_context,
            knowledge_query=knowledge_query,
            skill_context=skill_context,
            tool_context=tool_context,
            planner_state=planner_state,
            response_agent=response_agent,
            response_plan=response_plan,
        )
        used = (
            self.budget_counter.count(user_input)
            + self.budget_counter.count(skill_context)
            + self.budget_counter.count(knowledge_context)
            + self.budget_counter.count(bounded_memory)
            + history_chars
        )
        return BuiltAgentContext(
            messages=self.prompt_builder.build(prompt_context),
            selected_skills=selected_skills,
            budget=ContextBudgetUsage(
                mode=self.settings.context_budget_mode,
                unit="tokens" if token_mode else "chars",
                limit=total_limit,
                used=used,
                history_chars=history_chars,
                memory_chars=self.budget_counter.count(bounded_memory),
                knowledge_chars=self.budget_counter.count(knowledge_context),
                skill_chars=self.budget_counter.count(skill_context),
                truncated_sections=tuple(dict.fromkeys(truncated)),
            ),
        )

    def _take(self, text: str, section_limit: int, remaining: int, name: str, truncated: list[str]) -> tuple[str, int]:
        limit = max(0, min(section_limit, remaining))
        if self.budget_counter.count(text) > limit:
            truncated.append(name)
        value = self.budget_counter.take_head(text, limit)
        return value, max(0, remaining - self.budget_counter.count(value))

    def _fit_history(self, history: list[AiMessage], limit: int) -> list[AiMessage]:
        if limit <= 0:
            return []
        selected = []
        remaining = limit
        for message in reversed(history):
            if remaining <= 0:
                break
            content = self.budget_counter.take_tail(message.content, remaining)
            selected.append(AiMessage(role=message.role, content=content))
            remaining -= self.budget_counter.count(content)
        return list(reversed(selected))


def _format_knowledge_evidence(index: int, item) -> str:
    source = getattr(item, "source", "")
    score = getattr(item, "score", None)
    score_text = f", score={float(score):.4f}" if isinstance(score, (int, float)) else ""
    return f"[E{index}] source={source}{score_text}\n{getattr(item, 'content', '')}"
