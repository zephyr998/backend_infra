# Overview
AWS CDK is official toolkit in AWS that is designed for cloud engineers to create/update/manage/delete AWS cloud resources as a whole in a programmable approach. With CDK, we can easily deploy the cloud service infrastructure by simply define the resources we need and build connections between them. In this repo, we demonstrate how to build a general backend service infrastructure with API gateway, Load balancer, VPC, Auto Scaling Group, RDS, ECR, EventBridge and Lambda function. With this infrastructure setup, we solved the following problems:
1. create a proxy between client and backend service instance
2. auto scaling up/down backend service in auto scaling group using defined scaling rules
3. incoming traffic is evenly distributed to all available backend instances with load balancer
4. read and write database operations are separated and could scaled independently with backend service
5. CI/CD is achieved with github action, ECR, EventBridge and Lambda function
6. new created instance will be auto initialized with launch script

![alt text](image.png)