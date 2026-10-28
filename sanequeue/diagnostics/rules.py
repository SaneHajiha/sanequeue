"""Small explainable rules. Suspect duration is never a root-cause verdict."""
import math

RULE_VERSION = 'short-after-answer-v1'


def short_after_answer(visit, *, threshold_seconds=5):
    """Only completed, evidenced queue segments; not the whole conversation."""
    if type(threshold_seconds) not in (int, float) or not math.isfinite(threshold_seconds) or not 0 < threshold_seconds <= 60:
        raise ValueError('invalid_diagnostics_threshold')
    if visit.get('coverage') != 'observed' or visit.get('outcome') != 'answered':
        return None
    answered, ended, duration = (visit.get(key) for key in ('answered', 'ended', 'talk_seconds'))
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (answered, ended, duration)):
        return None
    if ended < answered or abs((ended - answered) - duration) > 2 or not duration < threshold_seconds:
        return None
    return dict(kind='short_after_answer', confidence='suspected', rule_version=RULE_VERSION,
                reason='short_completed_queue_segment', occurred_at=ended,
                observed_talk_seconds=duration, threshold_seconds=threshold_seconds,
                unit='queue_segment', root_cause='unavailable', human_intent='unavailable',
                limitations=['duration_does_not_prove_fault', 'queue_segment_is_not_whole_conversation'])
