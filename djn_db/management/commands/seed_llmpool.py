from django.core.management.base import BaseCommand
from django.utils import timezone

from djn_db.models import LLMPool

from djn_engine.pool import JURORS


def _infer_tags(cfg_name: str, model_id: str):
    s = f"{cfg_name} {model_id}".lower()
    tags = set()

    if "coder" in s or "code" in s:
        tags.add("coding")
    if "vl" in s or "vision" in s:
        tags.add("factual")
    if "plan" in s or "planner" in s:
        tags.add("planning")
    if "career" in s:
        tags.add("career")

    tags.add("general")
    return sorted(tags)


class Command(BaseCommand):
    help = "Seed/refresh LLMPool from djn_engine.pool.JURORS (idempotent upsert)."

    def handle(self, *args, **options):
        upserts = 0
        for cfg in JURORS:
            model_id = getattr(cfg, "model", "")
            if not model_id:
                continue

            name = getattr(cfg, "name", model_id)
            provider = getattr(cfg, "provider", "") or ""
            tags = _infer_tags(name, model_id)

            row, created = LLMPool.objects.get_or_create(
                model_id=model_id,
                defaults={
                    "name": name[:120],
                    "provider": provider[:60],
                    "enabled": True,
                    "tags_json": tags,
                    "category_weights_json": {},
                    "cost_tier": "",
                    "notes": "Seeded by seed_llmpool command.",
                    "created_at": timezone.now(),
                }
            )

            if not created:
                row.name = name[:120]
                row.provider = provider[:60]
                if not row.tags_json:
                    row.tags_json = tags
                row.updated_at = timezone.now()
                row.save(update_fields=["name", "provider", "tags_json", "updated_at"])

            upserts += 1

        self.stdout.write(self.style.SUCCESS(f"LLMPool seeded/refreshed: {upserts} models"))
        self.stdout.write("Run: python manage.py seed_llmpool")
