from aws_cdk import (
    Stack,
)
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ec2 as ec2
from constructs import Construct
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_iam as iam
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_apigatewayv2 as apigatewayv2
import aws_cdk
# from aws_cdk import core
from backend_infra.common import *
from aws_cdk.aws_apigatewayv2_integrations import HttpAlbIntegration

class BackendInfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # my_ecr_repo = ecr.Repository(self, 'MyECRRepository',
        #     repository_name='health_check',  # Provide a name for your ECR repository
        #     removal_policy=aws_cdk.RemovalPolicy.DESTROY
        # )

        # Create VPC
        vpc_cidr_block = '10.0.0.0/16'
        vpc = ec2.Vpc(self, 'MyVPC',
                      vpc_name='my-vpc',
                      ip_addresses=ec2.IpAddresses.cidr(vpc_cidr_block),
                        availability_zones=['us-west-2a','us-west-2b'],  # Number of Availability Zones, at least need to create two zones
                        subnet_configuration=[
                            ec2.SubnetConfiguration(
                                subnet_type=ec2.SubnetType.PUBLIC,
                                name='PublicSubnet',
                                cidr_mask=28
                            ),
                            # private subnet 
                            ec2.SubnetConfiguration(
                                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                                name='PrivateSubnet',
                                cidr_mask=24
                            )
                        ]
                    )
        
        # create ASG
        linux_image = ec2.GenericLinuxImage({
                        'us-west-2': 'ami-008fe2fc65df48dac',
                    })
        
        # ecr role will be attached to ASG instances
        # new created instance need ecr role permissions to pull ECR images for initialization
        ecr_role = iam.Role(self, 'ECRRole',
            assumed_by=iam.ServicePrincipal('ec2.amazonaws.com'),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEC2ContainerRegistryFullAccess')]
        )
        
        ecr_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'ecr:GetDownloadUrlForLayer',
                'ecr:BatchCheckLayerAvailability',
                'ecr:BatchGetImage',
                'ecr:InitiateLayerUpload',
                'ecr:UploadLayerPart',
                'ecr:CompleteLayerUpload',
                'ecr:PutImage',
                'ecr:GetAuthorizationToken',
                'ecr:DescribeImages'
            ],
            resources=['*'] # could specify the resource for stronger restrictions
        ))

        # Create security group and specify outbound rule
        my_security_group = ec2.SecurityGroup(self, 'MySecurityGroup',
            vpc=vpc,
            allow_all_outbound=True
        )

        # Add inbound rule for SSH from vpc
        # if associate_public_ip_address in asg is false then still cannot connect to instance using ssh connection in ec2 console
        # my_security_group.add_ingress_rule(ec2.Peer.ipv4(vpc_cidr_block), ec2.Port.tcp(22), 'Allow SSH')
        
        # Read user data script from file
        with open('launch_script.sh', 'r') as file:
            user_data_script = file.read()

        asg = autoscaling.AutoScalingGroup(self, 'MyAutoScalingGroup',
            vpc=vpc,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T2, ec2.InstanceSize.MICRO),
            machine_image=linux_image,
            min_capacity=1,
            max_capacity=3,
            desired_capacity=1,
            auto_scaling_group_name='my-asg',
            role=ecr_role,
            associate_public_ip_address=False,
            # setup volume later
            security_group=my_security_group,
            user_data=ec2.UserData.custom(user_data_script),
            # Use only private subnets for instances
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
        )

        # Create Load Balancer
        my_load_balancer = elbv2.ApplicationLoadBalancer(self, 'MyLoadBalancer',
            vpc=vpc,
            internet_facing=False,  # Set to False if internal
            load_balancer_name='myLB'
        )
        # test false, see if only allow traffic from vpc

        # Setup ASG as target of load balancer
        # Create a target group
        # when create target group, a security group will auto created, the source is LB, target is ASG with port 80
        # this will reflect in both LB and ASG
        target_group = elbv2.ApplicationTargetGroup(self, 'MyTargetGroup',
            vpc=vpc,
            port=80,
            targets=[asg],
            health_check=elbv2.HealthCheck(path='/health_check')
        )

        # Configure load balancer listener
        # listner will define the inbound rule/port
        # the reason why the LB dns name could be visited by anyone is that the 'open' param in add listner is true
        # should set to false then create vpc link and build integration between api gateway and LB
        listener = my_load_balancer.add_listener('MyListener',
            port=80,
            default_target_groups=[target_group],
            open=True
        )

        # Create vpc sg to allow outbound traffic
        vpc_link_security_group = ec2.SecurityGroup(self, 'vpcLinkSG',
            vpc=vpc,
            allow_all_outbound=True
        )
        
        # allow inbound http traffic
        vpc_link_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), 'Allow external traffic to vpc link')

        vpc_link = apigatewayv2.VpcLink(self,
                                        id='vpc_link',
                                        vpc=vpc,
                                        security_groups=[vpc_link_security_group],
                                        subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                                        vpc_link_name='myVpcLink')

        # # the API will route request from internet to LB, work as a proxy
        http_endpoint = apigatewayv2.HttpApi(self, 'httpProxyApi',
            default_integration=HttpAlbIntegration('DefaultIntegration', listener, vpc_link=vpc_link)
        )
