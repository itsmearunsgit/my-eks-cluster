from aws_cdk import (
    Stack,
    aws_eks as eks,
    aws_ssm as ssm,
    aws_iam as iam,
    aws_ec2 as ec2 
)
import json
import aws_cdk as cdk
from constructs import Construct
from aws_cdk.aws_eks import Cluster, KubernetesVersion
from aws_cdk.lambda_layer_kubectl import KubectlLayer
from aws_cdk.aws_iam import Role, ServicePrincipal, ManagedPolicy
from aws_cdk.aws_ec2 import Vpc, SubnetType
from aws_cdk import custom_resources as cr
from aws_cdk import aws_lambda as lambda_
from aws_cdk import CfnOutput
from aws_cdk import App, Stack
from aws_cdk import Aws


class MyEksClusterStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Create SSM Parameter
        environments_param = ssm.StringListParameter(self, "EnvironmentsParam",
                             parameter_name="/platform/account/env",
                             string_list_value=["prod","dev"],
                             tier=ssm.ParameterTier.ADVANCED)        

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
                {
                    "subnetType": SubnetType.PRIVATE_WITH_EGRESS,
                    "name": "Private",
                    "cidrMask": 24
                }
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
            default_capacity_instance=ec2.InstanceType("t3.medium"),
            default_capacity=1
        )
        
        # Create Custom Resource Lambda function to act as the provoider for custom resource
        custom_lambda_function = lambda_.Function(self, "CustomResourceHandler",
                    runtime=lambda_.Runtime.PYTHON_3_10,
                    handler="index.handler",
                    code=lambda_.Code.from_inline("""
import boto3
import json
                                                

def handler(event, context):
                                                 
   ssm_client = boto3.client('ssm')
   try:                                              
       response = ssm_client.get_parameter(Name='/platform/account/env', WithDecryption=False)
       # Get the list of values
       parameter_value = response['Parameter']['Value']
       values_list = parameter_value.split(',')                                        
       env_value = event['env']                                              
       print (env_value)                                        
       if env_value in values_list and env_value=="prod":
           replica_count = 2
       elif env_value in values_list and env_value=="dev":
           replica_count = 1
       else:
           replica_count = 1
       status = {"ReplicaCount": replica_count}                                               
       
       try:
            return({"Status": "SUCCESS", "Reason": "Custom Resource execution", "PhysicalResourceId": "CustomResourceId", 'Data': status})
       except Exception as e:
            return {
               'statusCode': 500,
               'Error': f"An unexpected error occurred: {str(e)}"
            }                                        
                                                       
                                                  
   except ssm_client.exceptions.ParameterNotFound as e:
        # Catch and handle the case where the parameter does not exist
        return {
            'statusCode': 400,
            'Error': f"Parameter '/platform/account/env' not found: {str(e)}"
        }
    
   except Exception as e:
        # Catch any other unexpected exceptions
        return {
            'statusCode': 500,
            'Error': f"An unexpected error occurred: {str(e)}"
        } 
                                                                                
                                    """))
        
        custom_lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks", "cloudformation:DescribeStackResources", "ssm:GetParameter"],
                resources=["*"]
            )
        )
        my_dict = {
            "env": "dev"
        }

        # Create Custom resource
        custom_resource = cr.AwsCustomResource(self, "CustomResource",
            on_create={
                "service": "Lambda",
                "action": "invoke",
                "parameters": {
                    "FunctionName": custom_lambda_function.function_name,
                    "InvocationType": "RequestResponse",
                    "Payload": json.dumps(my_dict)  
                            
                },
                "physical_resource_id": cr.PhysicalResourceId.of("CustomResourceId"),
            },
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[custom_lambda_function.function_arn],
                )
            ])
        )
        
        CfnOutput(self, "CustomResourceOutput", value=custom_resource.get_response_field("{'Data': {'status': ['ReplicaCount']}}"), export_name="Lambdacustomresourceoutput")
        
        replica_count_pod = custom_resource.get_response_field("{'Data': {'status': ['ReplicaCount']}}")
        
        # Create NginxIngress replicas using HELM chart
                                                      
        cluster.add_helm_chart("NginxIngress",
                               chart="ingress-nginx",
                               repository="https://kubernetes.github.io/ingress-nginx",
                               namespace="kube-system",
                               values={"controller": replica_count_pod})         

