from aws_cdk import core
from aws_cdk import aws_lambda as lambda_
from aws_cdk import custom_resources as cr

class MyCustomResourceStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Create Custom Resource Lambda function to act as the provoider for custom resource
        function = _lambda.Function(self, "CustomResourceHandler",
                    runtime=_lambda.Runtime.PYTHON_3_10,
                    handler="index.handler",
                    code=_lambda.Code.from_inline("""
import boto3
import json

def handler(event, context):
    ssm_client = boto3.client('ssm')
    response = ssm_client.get_parameter(Name='/platform/account/env', WithDecryption=False)
    # Get the list of values
    parameter_value = response['Parameter']['Value']
    values_list = parameter_value.split(',')
    if 'prod' in values_list:
        replica_count = 2
    elif 'dev' in values_list:
        replica_count = 1
    else:
        replica_count = 1
    return {'Data': {'ReplicaCount': replica_count}}
                                    """))

        # Create Custom Resource
        provider = cr.Provider(self, "CustomResourceProvider",
                               on_event_handler=function)

        custom_resource = cr.CustomResource(self, "CustomResource",
                                            service_token=provider.provoider_arn )

        replica_count_pod = custom_resource.get_att('ReplicaCount').to_string()

        # Deploy ingress-nginx Helm chart
        cluster.add_helm_chart("NginxIngress",
                               chart="ingress-nginx",
                               repository="https://kubernetes.github.io/ingress-nginx",
                               namespace="kube-system",
                               values={"controller": {"replicaCount": replica_count_pod}})