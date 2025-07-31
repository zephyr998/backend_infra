from aws_cdk import (
    Stack,
)
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_iam as iam
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_apigatewayv2 as apigatewayv2
import aws_cdk
from aws_cdk import RemovalPolicy, Duration, CfnOutput
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
                        'us-west-2': 'ami-075686beab831bb7f',
                    })
        
        # ecr role will be attached to ASG instances
        # new created instance need ecr role permissions to pull ECR images for initialization
        ecr_role = iam.Role(self, 'ECRRole',
            assumed_by=iam.ServicePrincipal('ec2.amazonaws.com'),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEC2ContainerRegistryFullAccess'),
                              iam.ManagedPolicy.from_aws_managed_policy_name('SecretsManagerReadWrite'),
                              iam.ManagedPolicy.from_aws_managed_policy_name('CloudWatchFullAccess'),
                              iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3FullAccess'),
                              iam.ManagedPolicy.from_aws_managed_policy_name('AmazonDynamoDBFullAccess'),
                              ]
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

        # first init security groups
        vpc_link_sg = ec2.SecurityGroup(self, 'vpc_link_sg',
            vpc=vpc,
            description="allow traffic from public to api gateway and AG to LB",
            allow_all_outbound=False
        )
        lb_sg = ec2.SecurityGroup(self, "lb_sg",
            vpc=vpc,
            description="Allow traffic from API Gateway to LB and LB to ASG",
            allow_all_outbound=False # need to explicitly set false otherwise egress rule will be ignored
        )
        asg_security_group = ec2.SecurityGroup(self, 'asg_sg',
            vpc=vpc,
            description="allow traffic from LB to ASG and ASG to public",
            allow_all_outbound=True
        )
        # Create a security group for the RDS instance
        db_security_group = ec2.SecurityGroup(self, 'DatabaseSG',
            vpc=vpc,
            description='Security group for RDS database',
            allow_all_outbound=True
        )

        # define inbound and outbound rules
        vpc_link_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "allow public inbound traffic")
        vpc_link_sg.add_egress_rule(lb_sg, ec2.Port.tcp(80), "allow outbound traffic to lb")

        lb_sg.add_ingress_rule(vpc_link_sg, ec2.Port.tcp(80), "Allow inbound traffic from API Gateway")
        lb_sg.add_egress_rule(asg_security_group, ec2.Port.tcp(80), "allow outbound traffic to asg")

        asg_security_group.add_ingress_rule(lb_sg, ec2.Port.tcp(80), "Allow inbound traffic from lb")        
        asg_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), 'Allow SSH')

        # Allow MySQL traffic (port 3306) from ASG instances to RDS
        db_security_group.add_ingress_rule(
            peer=asg_security_group,
            connection=ec2.Port.tcp(3306),
            description='Allow MySQL access from ASG instances'
        )
        
        # Create RDS database
        database = rds.DatabaseInstance(self, 'MyDatabase',
            engine=rds.DatabaseInstanceEngine.mysql(
                version=rds.MysqlEngineVersion.of(
                    mysql_full_version="8.0.40",
                    mysql_major_version="8.0"
                )
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3,
                ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[db_security_group],
            removal_policy=RemovalPolicy.DESTROY,  # For production, use SNAPSHOT or RETAIN
            deletion_protection=False,  # Set to True for production
            database_name='main',
            credentials=rds.Credentials.from_generated_secret(username='admin', 
                                                              secret_name='rds_credentials'),  # Auto-generates password
            # credentials=rds.Credentials.from_password(
            #     username="admin",
            #     password=aws_cdk.SecretValue.unsafe_plain_text("rdspassword")
            # ),
            backup_retention=Duration.days(7),  # Backup retention period
            storage_encrypted=True
        )

        # Get the secret reference
        secret = database.secret
        print('secret: {}'.format(secret.secret_name))

        # Read and modify launch script
        with open('launch_script.sh', 'r') as file:
            user_data_script = file.read()
            user_data_script = user_data_script.replace(
                '__DB_SECRET_ID__', 
                secret.secret_name
            )

        
        # Allow ASG instances to access RDS (outbound rule)
        asg_security_group.add_egress_rule(
            peer=db_security_group,
            connection=ec2.Port.tcp(3306),
            description='Allow outbound MySQL traffic to RDS'
        )
        
        # Output the database endpoint for reference
        CfnOutput(self, 'DatabaseEndpoint',
            value=database.db_instance_endpoint_address,
            description='Endpoint for the RDS database'
        )
        
        # Output the secret name for database credentials
        CfnOutput(self, 'DatabaseSecretName',
            value=database.secret.secret_name,
            description='Name of the Secrets Manager secret for database credentials'
        )

        asg = autoscaling.AutoScalingGroup(self, 'MyAutoScalingGroup',
            vpc=vpc,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T2, ec2.InstanceSize.MICRO),
            machine_image=linux_image,
            min_capacity=1,
            max_capacity=20,
            desired_capacity=1,
            auto_scaling_group_name='my-asg',
            role=ecr_role,
            associate_public_ip_address=True,
            # setup volume later
            security_group=asg_security_group,
            user_data=ec2.UserData.custom(user_data_script),
            # Use only private subnets for instances
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # Create Load Balancer
        my_load_balancer = elbv2.ApplicationLoadBalancer(self, 'MyLoadBalancer',
            vpc=vpc,
            internet_facing=False,  # Set to False if internal
            load_balancer_name='myLB',
            security_group=lb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
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
            open=False
        )

        vpc_link = apigatewayv2.VpcLink(self,
                                        id='vpc_link',
                                        vpc=vpc,
                                        security_groups=[vpc_link_sg],
                                        vpc_link_name='myVpcLink',
                                        subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS))

        # # the API will route request from internet to LB, work as a proxy
        http_endpoint = apigatewayv2.HttpApi(self, 'httpProxyApi',
            default_integration=HttpAlbIntegration('DefaultIntegration', listener, vpc_link=vpc_link)
        )
