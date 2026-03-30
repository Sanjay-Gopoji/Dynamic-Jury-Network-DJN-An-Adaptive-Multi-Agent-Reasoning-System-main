from django.db import models
from django.utils import timezone


class LLMPool(models.Model):
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=60, blank=True, default="")  
    model_id = models.CharField(max_length=160, unique=True)  
    enabled = models.BooleanField(default=True)

    tags_json = models.JSONField(default=list, blank=True)

    category_weights_json = models.JSONField(default=dict, blank=True)

    cost_tier = models.CharField(max_length=30, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.model_id})"


class DJNRun(models.Model):
    session_id = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(default=timezone.now)

    q_raw = models.TextField()
    user_constraints_json = models.JSONField(default=dict, blank=True)

    category = models.CharField(max_length=30, default="general")
    category_confidence = models.FloatField(default=0.0)
    missing_fields_json = models.JSONField(default=list, blank=True)

    clarifier_used = models.BooleanField(default=False)
    clarifier_questions_json = models.JSONField(default=list, blank=True)
    clarifier_answers_json = models.JSONField(default=list, blank=True)

    q_final = models.TextField(blank=True, default="")
    assumptions_json = models.JSONField(default=list, blank=True)

    jury_roster_json = models.JSONField(default=list, blank=True)
    role_map_json = models.JSONField(default=dict, blank=True)

    final_label = models.CharField(max_length=80, blank=True, default="")
    final_answer = models.TextField(blank=True, default="")
    final_confidence = models.CharField(max_length=10, blank=True, default="")
    stop_reason = models.CharField(max_length=40, blank=True, default="")

    user_feedback = models.SmallIntegerField(null=True, blank=True)

    duration_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"DJNRun {self.session_id} [{self.category}]"


class DJNRound(models.Model):
    run = models.ForeignKey(DJNRun, on_delete=models.CASCADE, related_name="rounds")
    round_index = models.PositiveSmallIntegerField()

    created_at = models.DateTimeField(default=timezone.now)

    agreement = models.FloatField(null=True, blank=True)
    majority_label = models.CharField(max_length=80, blank=True, default="")
    improvement = models.FloatField(null=True, blank=True)
    stagnation_flag = models.BooleanField(default=False)

    verdict_distribution_json = models.JSONField(default=dict, blank=True)
    tldr_similarity_score = models.FloatField(null=True, blank=True)
    effective_agreement_score = models.FloatField(null=True, blank=True)

    handoff_tldr_json = models.JSONField(default=dict, blank=True)

    latency_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("run", "round_index")]
        ordering = ["round_index"]
        constraints = [
        models.UniqueConstraint(fields=["run", "round_index"], name="uniq_run_roundindex"),
    ]

    def __str__(self):
        return f"Round {self.round_index} ({self.run.session_id})"


class JurorResponse(models.Model):
    round = models.ForeignKey(DJNRound, on_delete=models.CASCADE, related_name="juror_responses")

    juror_id = models.CharField(max_length=4)
    role = models.CharField(max_length=16, blank=True, default="")

    model = models.ForeignKey(LLMPool, on_delete=models.SET_NULL, null=True, blank=True)
    model_id_snapshot = models.CharField(max_length=160, blank=True, default="")

    verdict_label = models.CharField(max_length=80, blank=True, default="")
    tldr = models.TextField(blank=True, default="")
    reasoning_json = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=16, default="OK")
    schema_valid = models.BooleanField(default=True)
    error_msg = models.TextField(blank=True, default="")

    latency_ms = models.IntegerField(null=True, blank=True)
    token_in = models.IntegerField(null=True, blank=True)
    token_out = models.IntegerField(null=True, blank=True)
    cost_estimate = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("round", "juror_id")]
        ordering = ["juror_id"]
        constraints = [
            models.UniqueConstraint(fields=["round", "juror_id"], name="uniq_round_juror"),
        ]


    def __str__(self):
        return f"{self.juror_id} {self.verdict_label} ({self.round})"


class ModelRollingStat(models.Model):
    model = models.ForeignKey(LLMPool, on_delete=models.CASCADE, related_name="rolling_stats")
    category = models.CharField(max_length=30, default="general")

    appearances_total = models.IntegerField(default=0)
    user_accepts_total = models.IntegerField(default=0)

    user_acceptance_rate = models.FloatField(default=0.0)
    win_rate_in_majority = models.FloatField(default=0.0)
    disagreement_rate = models.FloatField(default=0.0)
    avg_latency_ms = models.FloatField(default=0.0)
    schema_valid_rate = models.FloatField(default=0.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("model", "category")]
        ordering = ["model__name", "category"]

    def __str__(self):
        return f"{self.model.name} [{self.category}]"
