def test_cancel_job_marks_failed():
    bp = __import__('batch_processor')
    inst = bp.batch_processor
    job_id = inst.create_job(1, 'analyze', ['a.py'])
    ok = inst.cancel_job(job_id)
    assert ok is True
    job = inst.get_job_status(job_id)
    assert job is not None
    assert job.status in ('failed',)
    assert 'canceled' in job.error_message

