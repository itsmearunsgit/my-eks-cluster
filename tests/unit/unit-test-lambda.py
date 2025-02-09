import pytest
import boto3
from moto import mock_ssm
from index import handler

@pytest.fixture
def ssm_setup():
    with mock_ssm():
        client = boto3.client('ssm')
        values_list = ["prod", "dev"]
        client.put_parameter(Name='/platform/account/env',  Value=','.join(values_list),Type='StringList', Overwrite=True)
        yield

def test_replica_count_production(ssm_setup):
    event = {}
    context = {}
    response = handler(event, context)
    assert response['Data']['ReplicaCount'] == 2
    
def test_replica_count_development(ssm_setup):
    event = {}
    context = {}
    response = handler(event, context)
    assert response['Data']['ReplicaCount'] == 1




