from django.contrib import admin
from .models import LLMPool, DJNRun, DJNRound, JurorResponse, ModelRollingStat


@admin.register(LLMPool)
class LLMPoolAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "model_id", "enabled")
    list_filter = ("enabled", "provider")
    search_fields = ("name", "model_id")


@admin.register(DJNRun)
class DJNRunAdmin(admin.ModelAdmin):
    list_display = ("session_id", "created_at", "category", "final_confidence", "stop_reason", "user_feedback")
    list_filter = ("category", "final_confidence", "stop_reason")
    search_fields = ("session_id", "q_raw", "q_final")


@admin.register(DJNRound)
class DJNRoundAdmin(admin.ModelAdmin):
    list_display = ("run", "round_index", "agreement", "majority_label", "improvement", "stagnation_flag", "latency_ms")
    list_filter = ("round_index", "stagnation_flag")


@admin.register(JurorResponse)
class JurorResponseAdmin(admin.ModelAdmin):
    list_display = ("round", "juror_id", "role", "verdict_label", "status", "schema_valid", "latency_ms")
    list_filter = ("status", "schema_valid", "role")
    search_fields = ("verdict_label", "tldr", "model_id_snapshot")


@admin.register(ModelRollingStat)
class ModelRollingStatAdmin(admin.ModelAdmin):
    list_display = ("model", "category", "appearances_total", "user_acceptance_rate", "avg_latency_ms", "schema_valid_rate")
    list_filter = ("category",)
