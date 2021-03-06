import boto3
import random

def handler(event, context):
    dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
    table = dynamodb.Table('noTriggerTestTable')
    for i in range(100):
        key = random.randint(1, 1000)
        item = table.get_item(Key={'id': key})
    return 'done'
