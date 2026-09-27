from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models.skill_registry import SkillRegistryAliasModel, SkillRegistryModel
from src.models.taxonomy import SkillTaxonomyItem


class SkillRegistryRepository:
    """Database access for stable skill identities and trusted aliases."""

    def __init__(self, db: Session):
        self.db = db

    def find_by_normalized_name(self, normalized_name: str) -> SkillRegistryModel | None:
        skill = (
            self.db.query(SkillRegistryModel)
            .filter(SkillRegistryModel.normalized_name == normalized_name)
            .first()
        )
        if skill:
            return skill

        alias = (
            self.db.query(SkillRegistryAliasModel)
            .filter(SkillRegistryAliasModel.normalized_alias == normalized_name)
            .first()
        )
        return self.db.get(SkillRegistryModel, alias.skill_id) if alias else None

    def bootstrap_seed(self, skills: list[SkillTaxonomyItem], normalize) -> None:
        """Idempotently register seed canonical IDs and their audited aliases."""
        changed = False
        occupied_keys = {
            value
            for (value,) in self.db.query(SkillRegistryModel.normalized_name).all()
        }
        occupied_keys.update(
            value
            for (value,) in self.db.query(SkillRegistryAliasModel.normalized_alias).all()
        )
        for item in skills:
            canonical_key = normalize(item.canonical_name)
            record = self.db.get(SkillRegistryModel, item.skill_id)
            if record is None:
                # A pre-existing observed entry wins over a later seed collision;
                # never silently replace a stable identity.
                record = self.find_by_normalized_name(canonical_key)
                if record is None:
                    record = SkillRegistryModel(
                        skill_id=item.skill_id,
                        canonical_name=item.canonical_name,
                        normalized_name=canonical_key,
                        category=item.category,
                        source="seed",
                    )
                    self.db.add(record)
                    occupied_keys.add(canonical_key)
                    changed = True

            for alias_name in item.aliases:
                alias_key = normalize(alias_name)
                # Several historical seed aliases differ only by casing. They
                # are one trusted normalized alias, not duplicate DB rows.
                if not alias_key or alias_key in occupied_keys:
                    continue
                self.db.add(
                    SkillRegistryAliasModel(
                        skill_id=record.skill_id,
                        alias_name=alias_name,
                        normalized_alias=alias_key,
                    )
                )
                occupied_keys.add(alias_key)
                changed = True

        if changed:
            self.db.commit()

    def create_observed(
        self,
        canonical_name: str,
        normalized_name: str,
        category: str | None = None,
    ) -> SkillRegistryModel:
        """Create a UUID-backed identity, reusing a concurrent creator's row."""
        existing = self.find_by_normalized_name(normalized_name)
        if existing:
            return existing

        record = SkillRegistryModel(
            canonical_name=canonical_name,
            normalized_name=normalized_name,
            category=category,
            source="observed",
        )
        self.db.add(record)
        try:
            self.db.commit()
            self.db.refresh(record)
            return record
        except IntegrityError:
            self.db.rollback()
            existing = self.find_by_normalized_name(normalized_name)
            if existing:
                return existing
            raise

    def add_trusted_aliases(self, skill_id: str, aliases: tuple[str, ...], normalize) -> None:
        """Persist source-declared aliases without replacing an existing identity."""
        changed = False
        seen: set[str] = set()
        for alias_name in aliases:
            alias_key = normalize(alias_name)
            if not alias_key or alias_key in seen:
                continue
            seen.add(alias_key)
            existing = self.find_by_normalized_name(alias_key)
            if existing:
                # A pre-existing identity always wins over an implicit merge.
                # This resolver never performs semantic or destructive merges.
                continue
            self.db.add(
                SkillRegistryAliasModel(
                    skill_id=skill_id,
                    alias_name=alias_name,
                    normalized_alias=alias_key,
                )
            )
            changed = True
        if changed:
            self.db.commit()
