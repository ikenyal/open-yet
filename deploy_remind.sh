#!/bin/zsh
# Creates the "after" version next to the untouched "before" function `open-yet`.
# Usage: AWS_PROFILE=... ./deploy_remind.sh you@example.com
set -euo pipefail
EMAIL=${1:?email address to notify}
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
FN=open-yet-remind
TOPIC=open-yet-remind
FN_ROLE=open-yet-remind-fn-role
SCHED_ROLE=open-yet-remind-scheduler-role

# 1. SNS topic + email subscription (confirm the email AWS sends you)
TOPIC_ARN=$(aws sns create-topic --name $TOPIC --region $REGION --query TopicArn --output text)
if ! aws sns list-subscriptions-by-topic --topic-arn $TOPIC_ARN --region $REGION \
     --query 'Subscriptions[].Endpoint' --output text | grep -qF "$EMAIL"; then
  aws sns subscribe --topic-arn $TOPIC_ARN --protocol email --notification-endpoint "$EMAIL" --region $REGION >/dev/null
fi

# 2. Role EventBridge Scheduler assumes: may publish to this one topic only
aws iam create-role --role-name $SCHED_ROLE --assume-role-policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",
  \"Principal\":{\"Service\":\"scheduler.amazonaws.com\"},\"Action\":\"sts:AssumeRole\",
  \"Condition\":{\"StringEquals\":{\"aws:SourceAccount\":\"$ACCOUNT\"}}}]}" >/dev/null 2>&1 || true
aws iam put-role-policy --role-name $SCHED_ROLE --policy-name publish --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sns:Publish\",
  \"Resource\":\"$TOPIC_ARN\"}]}"
SCHED_ROLE_ARN=arn:aws:iam::${ACCOUNT}:role/$SCHED_ROLE

# 3. Role for the new function: Bedrock (Nova Pro), create schedules named open-yet-*,
#    and pass only the scheduler role. Nothing else.
aws iam create-role --role-name $FN_ROLE --assume-role-policy-document '{
  "Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null 2>&1 || true
aws iam attach-role-policy --role-name $FN_ROLE \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name $FN_ROLE --policy-name remind --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":[\"bedrock:InvokeModel\",\"bedrock:InvokeModelWithResponseStream\"],
    \"Resource\":\"arn:aws:bedrock:${REGION}::foundation-model/amazon.nova-pro-v1:0\"},
   {\"Effect\":\"Allow\",\"Action\":\"scheduler:CreateSchedule\",
    \"Resource\":\"arn:aws:scheduler:${REGION}:${ACCOUNT}:schedule/default/open-yet-*\"},
   {\"Effect\":\"Allow\",\"Action\":\"iam:PassRole\",\"Resource\":\"$SCHED_ROLE_ARN\",
    \"Condition\":{\"StringEquals\":{\"iam:PassedToService\":\"scheduler.amazonaws.com\"}}}]}"

# 4. Package: dependencies for the Lambda runtime (built once into build/), plus the code
if [[ ! -d build ]]; then
  python3 -m pip install -q -r requirements.txt -t build --platform manylinux2014_x86_64 \
    --only-binary=:all: --python-version 3.12 --implementation cp
fi
rm -rf build-remind function-remind.zip
cp -R build build-remind
cp agent.py remind.py build-remind/
(cd build-remind && zip -qr ../function-remind.zip . -x '__pycache__/*' '*/__pycache__/*')

ENV="Variables={REMIND_TOPIC_ARN=$TOPIC_ARN,REMIND_SCHEDULER_ROLE_ARN=$SCHED_ROLE_ARN}"
if aws lambda get-function --function-name $FN --region $REGION >/dev/null 2>&1; then
  aws lambda update-function-code --function-name $FN --zip-file fileb://function-remind.zip --region $REGION >/dev/null
  aws lambda wait function-updated --function-name $FN --region $REGION
  aws lambda update-function-configuration --function-name $FN --environment "$ENV" --region $REGION >/dev/null
else
  sleep 10  # let the new role propagate
  aws lambda create-function --function-name $FN --runtime python3.12 --architectures x86_64 \
    --handler agent.handler --role arn:aws:iam::${ACCOUNT}:role/$FN_ROLE \
    --timeout 90 --memory-size 1024 --zip-file fileb://function-remind.zip \
    --environment "$ENV" --region $REGION >/dev/null
fi
aws lambda wait function-updated --function-name $FN --region $REGION
echo "deployed $FN; topic $TOPIC_ARN"
