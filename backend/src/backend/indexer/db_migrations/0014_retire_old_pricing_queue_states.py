from yoyo import step


# One-time conversion. The current worker leaves in-flight jobs pending, so
# ordinary restarts never need a separate processing/recovery state.
steps = [step("""
    UPDATE pricing_capture_queue SET status = 'pending', next_attempt_at = 0
    WHERE status = 'processing'
"""), step("""
    DELETE FROM pricing_capture_queue
    WHERE status NOT IN ('pending', 'failed')
       OR (status = 'failed' AND next_attempt_at IS NULL)
""")]
