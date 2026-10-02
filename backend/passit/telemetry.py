"""Measure calls independently of story transactions, without recording private content."""

import logging
import time
from contextvars import ContextVar
from decimal import Decimal

from sqlalchemy import select

from .models import AICall, now

log = logging.getLogger(__name__)
usage_context = ContextVar("ai_usage", default=None)


def capture_usage(usage):
    values = usage_context.get()
    if values is None or not isinstance(usage, dict):
        return
    for source, target in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens")):
        count = usage.get(source)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            values[target] = count


def measured_generate(
    db, adapter, profile, task, context, *, chain_id=None, work_item_id=None, purpose="game"
):
    started_at, clock = now(), time.monotonic()
    usage = {"input_tokens": None, "output_tokens": None}
    token = usage_context.set(usage)
    succeeded, error_code = False, None
    try:
        result = adapter.generate(profile, task, context)
        succeeded = True
        return result
    except Exception as exc:
        error_code = type(exc).__name__
        raise
    finally:
        usage_context.reset(token)
        elapsed = max(0, round((time.monotonic() - clock) * 1000))
        cost = None
        if profile.provider == "demo":
            usage = {"input_tokens": 0, "output_tokens": 0}
            cost = Decimal(0)
        elif all(usage[k] is not None for k in usage) and all(
            getattr(profile, k) is not None for k in ("input_price_per_million", "output_price_per_million")
        ):
            cost = (
                Decimal(usage["input_tokens"]) * Decimal(str(profile.input_price_per_million))
                + Decimal(usage["output_tokens"]) * Decimal(str(profile.output_price_per_million))
            ) / Decimal(1000000)
        try:
            with db.transaction() as s:
                is_retry = bool(
                    work_item_id
                    and s.scalar(select(AICall.id).where(AICall.work_item_id == work_item_id).limit(1))
                )
                s.add(
                    AICall(
                        profile_id=profile.id,
                        provider=profile.provider,
                        task=task,
                        chain_id=chain_id,
                        work_item_id=work_item_id,
                        purpose=purpose,
                        started_at=started_at,
                        duration_ms=elapsed,
                        succeeded=succeeded,
                        is_retry=is_retry,
                        error_code=error_code,
                        estimated_cost_usd=cost,
                        **usage,
                    )
                )
        except Exception as exc:
            # A measurement failure must not discard a valid result or trigger another paid call.
            log.warning("AI measurement unavailable (%s)", type(exc).__name__)
