דוגמאות טסטים – Rate Limiting ואסינכרוניות
============================================

Rate Limiting (Redis Mock)
--------------------------

.. code-block:: python

   @pytest.mark.asyncio
   async def test_rate_limit_soft_warning(monkeypatch):
       # Arrange limiter to low limit and drive to 80%
       ...

טסטים אסינכרוניים
------------------

.. code-block:: python

   @pytest.mark.asyncio
   async def test_async_flow():
       result = await some_async_function()
       assert result
