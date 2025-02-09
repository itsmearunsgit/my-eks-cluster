from aws_cdk import (
    Stack,
    aws_eks as eks,
    aws_ssm as ssm,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ec2 as ec2
)
from constructs import Construct
from aws_cdk.aws_eks import Cluster, KubernetesVersion
from aws_cdk.lambda_layer_kubectl import KubectlLayer
from aws_cdk.aws_iam import Role, ServicePrincipal, ManagedPolicy
from aws_cdk.aws_ec2 import Vpc, SubnetType

class MyEksClusterStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Create SSM Parameter
        environments_param = ssm.StringListParameter(self, "EnvironmentsParam",
                             parameter_name="/platform/account/env",
                             string_list_value=["prod","dev"],
                             tier=ssm.ParameterTier.ADVANCED)        
        #prod_param_count = ssm.StringParameter(self, "AccountEnvParam",
            #parameter_name="/platform/account/production",
            #string_value="2")  # SSM parameter for production
        #core.Tags.of(prod_param_count).add("Environment", "Prod")

        #dev_param_count = ssm.StringParameter(self, "AccountEnvParamdev",
            #parameter_name="/platform/account/development",
            #string_value="1")  # SSM parameter for development
        #core.Tags.of(dev_param_count).add("Environment", "Dev")
        
        # Define the VPC
        vpc = Vpc(
            self, "EksVpc",
            max_azs=3,  # Default is all AZs in the region
            subnet_configuration=[
                {
                    "subnetType": SubnetType.PUBLIC,
                    "name": "Public",
                    "cidrMask": 24
                },  
            ]
        )
        # Define the IAM role for the EKS cluster
        eks_role = Role(
            self, 'EksClusterRole',
            assumed_by=ServicePrincipal('eks.amazonaws.com'),
            managed_policies=[
                ManagedPolicy.from_aws_managed_policy_name('AmazonEKSClusterPolicy'),
                ManagedPolicy.from_aws_managed_policy_name('AmazonEKSServicePolicy')
            ],
            role_name="eks_service_role"
        )
        kubectl_layer = KubectlLayer(self, "KubectlLayer")
        
        #Define the EKS cluster
        cluster = eks.Cluster(
            self, "EKSWelcome", 
            version=eks.KubernetesVersion.V1_30,
            kubectl_layer=kubectl_layer,
            cluster_name= "eks-cdk-cluster",
            masters_role=eks_role,
            vpc=vpc,
            default_capacity_instance=aws_ec2.InstanceType("t3.medium"),
            default_capacity=1
        )

        # Create Custom Resource Lambda
        function = _lambda.Function(self, "CustomResourceHandler",
                    runtime=_lambda.Runtime.PYTHON_3_13,
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
                                            service_token=provider.service_token)

        replica_count_pod = custom_resource.get_att('ReplicaCount').to_string()

        # Deploy ingress-nginx Helm chart
        eks-cdk-cluster.add_helm_chart("NginxIngress",
                               chart="ingress-nginx",
                               repository="https://kubernetes.github.io/ingress-nginx",
                               namespace="kube-system",
                               values={"controller": {"replicaCount": replica_count_pod}})