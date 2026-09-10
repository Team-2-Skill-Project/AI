
from pydantic import BaseModel, Field


class SkillTaxonomyItem(BaseModel):
    skill_id: str = Field(..., description="Unique skill identifier, e.g. skill_python")
    canonical_name: str = Field(..., description="Official standard name of the skill")
    category: str = Field(..., description="Skill category, e.g. Programming Languages, Databases")
    aliases: list[str] = Field(default_factory=list, description="Common aliases, acronyms, or variations")
    parent_skill_id: str | None = Field(default=None, description="Optional parent category/skill id")
