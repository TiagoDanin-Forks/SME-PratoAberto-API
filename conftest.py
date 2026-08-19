# coding: utf-8
import os

import pytest

os.environ.setdefault('API_MONGO_URI', 'localhost:27017')


@pytest.fixture
def app():
    import api
    app = api.app
    app.debug = True
    return app
