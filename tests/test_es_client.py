from backend.services.es_client import ESClient


def test_should_build_url_with_path():
    client = ESClient(base_url="https://es.example.com:9200", username="", password="")
    assert client._build_url("/_cluster/health") == "https://es.example.com:9200/_cluster/health"


def test_should_strip_trailing_slash_from_base_url():
    client = ESClient(base_url="https://es.example.com:9200/", username="", password="")
    assert client._build_url("/_cat/indices") == "https://es.example.com:9200/_cat/indices"


def test_should_build_auth_tuple_when_credentials_provided():
    client = ESClient(base_url="https://es:9200", username="elastic", password="secret")
    assert client._auth == ("elastic", "secret")


def test_should_have_no_auth_when_credentials_empty():
    client = ESClient(base_url="https://es:9200", username="", password="")
    assert client._auth is None
