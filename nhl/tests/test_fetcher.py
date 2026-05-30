import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from nhl.data.fetcher import api_get

def test_api_get_success():
    """Vérifie que la requête retourne du JSON en cas de succès 200."""
    async def run_test():
        session = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"test": "data"})
        
        session.get.return_value.__aenter__.return_value = mock_resp
        
        res = await api_get(session, "http://fake.url")
        assert res == {"test": "data"}
    
    asyncio.run(run_test())

@patch('nhl.data.fetcher.asyncio.sleep')
def test_api_get_retry_429(mock_sleep):
    """Vérifie que le système effectue un retry exponentiel en cas de HTTP 429."""
    async def run_test():
        session = MagicMock()
        
        mock_resp_429 = AsyncMock()
        mock_resp_429.status = 429
        
        mock_resp_200 = AsyncMock()
        mock_resp_200.status = 200
        mock_resp_200.json = AsyncMock(return_value={"success": True})
        
        session.get.return_value.__aenter__.side_effect = [mock_resp_429, mock_resp_200]
        
        res = await api_get(session, "http://fake.url")
        assert res == {"success": True}
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(2) # 2**1
        
    asyncio.run(run_test())
