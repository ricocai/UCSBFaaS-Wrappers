import json,time,os,sys,argparse,statistics,ast
from pprint import pprint
from graphviz import Digraph
from enum import Enum
from collections import defaultdict

#tuple object enumeration (positions)
TYPE='typ' #fn,sdk,sdkT (sdkTrigger)
REQ='req'
PAYLOAD='pl'
TS='ts'
SEQ='seqNo'
DUR='dur'
CHILDREN='children'
SSID='ssegId'
SSPID='ssegPid'
TRID='traceId'

DEBUG = True
REQS = {}
SUBREQS = {} #for functions triggered (in/)directly by other functions
TRIGGERS = defaultdict(list)
SDKS = []
SUBSEGS = {} #subsegment_id: object
eleID = 1
seqID = 1
NODES = {}
##################### getName #######################
def getName(reqObj,INST=False):
    '''Given an object (reqObj), return a unique name for the node
       if INST is True, then add an 8 digit uuid to end of name so that 
       its different from all others (non-aggregated)

       name cannot contain colons as graphviz doesn't handle them in a node name, 
       name can have newlines however
       reqObj = {TYPE:'sdkT',REQ:reqID,SSID:myid,SSPID:pid,TRID:trid,PAYLOAD:rest_dict,TS:start_ts,DUR:0.0,SEQ:seqID,CHILDREN:[]}
       pl = reqObj[PAYLOAD]
       pl['reg'] #region of this function
       pl['name'] #this fn's (callee) name
       pl['tname'] #caller's name, table name, s3 bucket name, snstopic, url
       pl['kn']  #caller reqID, keyname, s3 prefix, sns subject, http_method
       pl['op']' #triggering_operation:source_region
       pl['key'] #unused for fn, key for ddb, filename for s3, unused for sns, unused for http
       pl['rest'] #other info only for event sources

       match is the subportion of name that lets us match SDK calls to triggers

    '''
    
    pl = reqObj[PAYLOAD]
    match = '{}:{}:{}'.format(pl['tname'],pl['kn'],pl['key']) #key is none if unused

    typ = reqObj[TYPE]
    opreg = pl['reg']
    ntoks = pl['op'].split(':')
    op = ntoks[0]
    reg = ntoks[1]
    path = 'ERR'
    if typ == 'fn': 
        name='FN={} {}'.format(pl['name'],pl['reg'])
        if op == 'none':
            match = '{}:{}'.format(pl['tname'],pl['name']) #triggered by a function caller:callee
        elif op == 'Invoke':
            match = '{}:{}'.format(pl['name'],pl['tname']) #triggered by a function caller:callee
        #else use the default match above
    else: #sdk
        if op == 'Invoke':
            path = '{}'.format(pl['tname'])
            match = '{}:{}'.format(pl['tname'],pl['name']) #triggered by a function caller:callee
            name='{} {} {} {}'.format(op,opreg,path,typ)
        elif op.startswith('S3='):
            path = '{}/{}/{}'.format(pl['tname'],pl['kn'],pl['key'])
            name='{} {} {} {}'.format(op,opreg,path,typ)
        elif op.startswith('DDB='):
            path = '{} {}={}'.format(pl['tname'],pl['kn'],pl['key'])
            name='{} {} {} {}'.format(op,opreg,path,typ)
        elif op.startswith('SNS='):
            path = '{} {}'.format(pl['tname'],pl['kn'])
            name='{} {} {} {}'.format(op,opreg,path,typ)
        elif op.startswith('HTTP='):
            path = '{} {}'.format(pl['tname'],pl['kn'])
            name='{} {} {} {}'.format(op,opreg,path,typ)
        else:
            print(pl)
            assert False #we shouldn't be here

    if INST:
        name+='_{}'.format(str(uuid.uuid4())[:8]) #should this be requestID?
    return name,match

##################### processDotChild #######################
def processDotChild(dot,req):
    global eleID
    dur = req[DUR]
    name,_ = getName(req)
    if name.startswith('NONTRIGGER:'):
        name = name[11:]
        totsum = dur
        count = 1
        if name in NODES:
            (t,c) = NODES[name]
            totsum+=t
            count += c
        NODES[name] = (totsum,count)
        avg = totsum/count 
        nodename = '{}\navg: {:0.1f}ms'.format(name,avg)
        dot.node(name,nodename,fillcolor='gray',style='filled')
    else:
        totsum = dur
        count = 1
        if name in NODES:
            (t,c) = NODES[name]
            totsum+=t
            count += c
        NODES[name] = (totsum,count)
        avg = totsum/count 
        nodename='{}\navg: {:0.1f}ms'.format(name,avg)
        dot.node(name,nodename)
    eleID += 1
    for child in req[CHILDREN]:
        child_name = processDotChild(dot,child)
        dot.edge(name,child_name)
    return name

##################### makeDotAggregate #######################
def makeDotAggregate():
    global eleID
    dot = Digraph(comment='GRAggregate',format='pdf')
    agent_name = "Clients"
    dot.node(agent_name,agent_name)
    agent_edges = []

    #req = {TYPE:'fn,sdk,sdkT',REQ:reqID,PAYLOAD:pl,TS:ts,DUR:dur,CHILDREN:[]}
    for key in REQS:
        req = REQS[key]
        pl = req[PAYLOAD]
        name,_ = getName(req)
        dur = req[DUR]
        totsum = dur
        count = 1
        if name in NODES:
            (t,c) = NODES[name]
            totsum+=t
            count += c
        NODES[name] = (totsum,count)
        avg = totsum/count 
        nodename='{}\navg: {:0.1f}ms'.format(name,avg)
        dot.node(name,nodename)
        if name not in agent_edges: 
            dot.edge(agent_name,name)
            agent_edges.append(name)
        eleID += 1

        for child in req[CHILDREN]:
            child_name = processDotChild(dot,child)
            dot.edge(name,child_name)

    dot.render('gragggraph', view=True)
    return

##################### processEventSource #######################
def processEventSource(pl):
    ''' returns True/False, payload as dict:
        	    # for different operations, order is: Fn, DDB, S3, SNS, HTTP with .amazonaws.com in url
        retn['reg'] #region of this function
        retn['name'] #this fn's (callee) name
        retn['tname'] #caller's name, table name, s3 bucket name, snstopic, url
        retn['kn']  #caller reqID, keyname, s3 prefix, sns subject, http_method
        retn['op']' #triggering_operation:source_region
        retn['key'] #unused for fn, key for ddb, filename for s3, unused for sns, unused for http
        retn['rest'] #other info only for event sources
    '''
    toks = pl.split(':')
    retn = {'name': toks[7], 'reg': toks[4], 'rest':'none', 'key':'none', 'kn':'none'} #potentially unused keys
    triggered = False
    if pl.startswith('pl:arn:aws:lambda:') and (len(toks) == 8 or pl.endswith(':es:ext:invokeCLI')): #normal Invoke with unknown trigger
        retn['tname'] = 'none'
        retn['op'] = 'none:{}'.format(toks[4])
        pass
    elif ':es:lib:invokeCLI:' in pl: #Invoke trigger
        triggered = True
        #pl:arn:aws:lambda:us-west-2:443592014519:function:emptyB:es:lib:invokeCLI:FnInvokerPyB:ed086648-aa47-11e7-a1cd-4dab0b1999f4
        retn['op'] = 'Invoke:{}'.format(toks[4]) #triggering_operation:source_region
        retn['tname'] = toks[11] #caller's name
        retn['kn'] = toks[12] #caller reqID
        #key 'key', 'rest' not used

    elif ':ddb:' in pl: #DDB update trigger
        triggered = True
        #pl:arn:aws:lambda:us-west-2:443592014519:function:DBSyncPyB:esARN:arn:aws:dynamodb:us-west-2:443592014519:table/image-proc-B/stream/2017-10-05T21:42:44.663:es:ddb:keys:id:{"S": "imgProc/d1.jpg1428"}:op:INSERT
	#get tablename
        assert pl.find('esARN:') != -1
        tmp_tname = toks[14].split('/')
        retn['tname'] = tmp_tname[1] #table name
        retn['kn'] = toks[20] #key name
        retn['key'] = toks[22].strip(' "}') #key
        retn['rest'] = '{}:{}:{}'.format(tmp_tname[3],toks[15],toks[16]) #stream ID
        retn['op'] = 'DDB={}:{}'.format(toks[24],toks[12]) #triggering_op:source_region
        print('here! {}'.format(retn))
    else:
        print(pl)
        assert False
        #for HTTP the source region must be the same as this functions region because APIGW can only invoke functions in its region
    return triggered,retn

##################### processPayload #######################
def processPayload(pl,reqID): #about to do something that can trigger a lambda function
    ''' returns payload as dict:
        	    # for different operations, order is: Fn, DDB, S3, SNS, HTTP with .amazonaws.com in url
        retn['reg'] #region of operation target
        retn['name'] #this fn's name
        retn['tname'] #callee's name, table name, s3 bucket name, snstopic, url
        retn['kn']  #unused for fn, keyname, s3 prefix, sns subject, unused for http
        retn['op']' #triggering_operation:current_region
        retn['key'] #unused for fn, key for ddb, filename for s3, unused for sns, unused for http
    '''
    #PutItem:us-west-2:TableName:image-proc-B:Item:{"id": "imgProc/d1.jpg0b92", "labels": "[{"Name": "Animal", "Confidence": 96.52117156982422}, {"Name": "Gazelle", "Confidence": 96.52117156982422}, {"Name": "Impala", "Confidence": 96.52117156982422}, {"Name": "Mammal", "Confidence": 96.52117156982422}, {"Name": "Wildlife", "Confidence": 96.52117156982422}, {"Name": "Deer", "Confidence": 91.72703552246094}]"}
    #ops include [ 'PutItem', 'UpdateItem', 'DeleteItem', 'BatchWriteItem', 'PutObject', 'DeleteObject', 'PostObject', 'Publish', 'Invoke' ]
    pl = pl.strip('"}')
    if DEBUG: 
        print('ppayload: {}'.format(pl))

    #get the enclosing functions details
    if reqID in REQS:
        me = REQS[reqID]
    else: 
        me = SUBREQS[reqID]
    toks = pl.split(':')
    current_region = me['pl']['reg']
    nm = me['pl']['name']
    retn = {'name': nm, 'reg': toks[1], 'rest':'none', 'key':'none', 'kn':'none'} #potentially unused keys

    if pl.startswith('PutItem:'):
        retn['op'] = 'DDB=PutItem:{}'.format(current_region)
        rest = pl[8:]
        idx = rest.find(':TableName:')
        assert idx != -1
        idx2 = rest.find(':Item:')
        assert idx2 != -1
        retn['tname'] = rest[idx+11:idx2]
        data = rest[idx2+7:] #7 to get past the {
        toks = data.split(': ')
        retn['kn'] = toks[0].strip('"')
        toks = toks[1].split(' ')
        retn['key'] = toks[0].strip('",')
        #'rest' is unused

    elif pl.startswith('UpdateItem:'):
        retn['op'] = 'DDB=UpdateItem'
        print(pl)
        sys.exit(1)

    elif pl.startswith('DeleteItem:'):
        retn['op'] = 'DDB=DeleteItem'
        print(pl)
        sys.exit(1)

    elif pl.startswith('BatchWriteItem:'):
        retn['op'] = 'DDB=BatchWriteItem'
        print(pl)
        sys.exit(1)

    elif pl.startswith('PutObject:'):
        retn['op'] = 'S3=PutObject'
        print(pl)
        sys.exit(1)

    elif pl.startswith('DeleteObject:'):
        retn['op'] = 'S3=DeleteObject'
        print(pl)
        sys.exit(1)

    elif pl.startswith('PostObject:'):
        retn['op'] = 'S3=PostObject'
        print(pl)
        sys.exit(1)

    elif pl.startswith('Publish:'):
        retn['op'] = 'SNS=Publish'
        print(pl)
        sys.exit(1)

    elif pl.startswith('Invoke:'):
        #Invoke:us-west-2:FunctionName:arn:aws:lambda:us-west-2:443592014519:function:emptyB:InvocationType:Event
        retn['op'] = 'Invoke:{}'.format(current_region)
        toks = pl.split(':')
        retn['reg'] = toks[1] #region of both
        retn['tname'] = toks[9]  #callee name
        retn['kn'] = reqID  #caller reqID
        retn['rest'] = '{}'.format(toks[11]) #invocationType
        assert toks[1] == toks[6] #make sure they are in the same region
        #key 'key' not used

    elif pl.startswith('HTTP:'):
        #HTTP:us-west-2:POST:http://httpbin.org/post
        #API Gateway url: https://6w1s7kyypi.execute-api.us-west-2.amazonaws.com/beta
        url = toks[3]
        assert url.startswith('http')
        incr = 7
        if url.startswith('https://'):
            incr += 1
        if url.find('amazonaws.com') != -1 and url.find('execute_api') != -1:
            #url is an api-gateway and thus potential trigger
            url = url[incr:] 
            urltoks = url.split('.')
            retn['op'] = 'HTTP:{}'.format(current_region)
            retn['reg'] = urltoks[2] #region (api gateway urls can only invoke functions in the same region)
            retn['tname'] = url
            retn['kn'] = toks[2] #method
            #key 'key' not used
        else:
            #todo: turn this on once old logs are gone
            #assert False
            retn = None
    else:
        assert False

    return retn
    
##################### processHybrid  #######################
def processHybrid(fname):
    flist = []
    #get the json from the files
    if os.path.isfile(fname):
        flist.append(fname)
    else:
        path = os.path.abspath(fname)
        for file in os.listdir(fname):
            fn = os.path.join(path, file)
            if os.path.isfile(fn) and fn.endswith('.xray'):
                flist.append(fn)

    for fname in flist:
        if DEBUG:
            print('processing xray file {}'.format(fname))
        with open(fname,'r') as f:
            json_dict = json.load(f)

        traces = json_dict['Traces']
        for trace in traces:
            segs = trace['Segments']
            for seg in segs:
                doc_dict = json.loads(seg['Document'])
                name = doc_dict['name']
                myid = seg['Id']
                if 'trace_id' in doc_dict:
                    trid = doc_dict['trace_id']
                #print(myid,doc_dict)
                start = doc_dict['start_time']
                end = doc_dict['end_time']
                if 'aws' in doc_dict:
                    aws = doc_dict['aws']
                    tname = op = reg = pl = 'unknown'
                    if 'operation' in aws:
                        op = aws['operation']
                    origin = doc_dict['origin']
                    #if origin == 'AWS::DynamoDB::Table':  #just a repeat of what we get in the subsegments
                    if origin == 'AWS::Lambda' and 'resource_arn' in doc_dict:
                        print('{} LAMBDA:{}:{}:{}:{}'.format(myid,doc_dict['resource_arn'],aws['request_id'],start,end))
                        print('\ttrid: {}'.format(trid))
                    else:
                        if 'function_arn' in aws:
                            print('{} FN:{}:{}:{}'.format(myid,aws['function_arn'],start,end))
                            print('\ttrid: {}'.format(trid))
                        else:
                            pass #can skip this as data is repeated
                            #if name != 'DynamoDB': #data is repeated here
                                #print('{} other_{}:{}:{}:{}'.format(myid,name,origin,start,end))
                                #print(doc_dict)
    
                    if 'subsegments' in doc_dict:
                        for subs in doc_dict['subsegments']:
                            subid = subs['id']
                            name = subs['name']
                            if 'aws' in subs:
                                #print('\t{}:{}:{}:{}:{}'.format(subs['name'],subs['aws']['operation'],subs['aws']['region'],subs['start_time'],subs['end_time']))
                                aws = subs['aws']
                                trid=myid=tname=op=reg='unknown'
                                if 'function_arn' in aws:
                                    fn = aws['function_arn']
                                if 'trace_id' in aws:
                                    trid = aws['trace_id']
                                if 'operation' in aws:
                                    op = aws['operation']
                                if 'table_name' in aws:
                                    tname = aws['table_name']
                                if 'region' in aws:
                                    reg = aws['region']
                                key=keyname='unknown'
                                if 'gr_payload' in aws:
                                    pl = aws['gr_payload']
                                    idx = pl.find(':Item:{')
                                    idx3 = pl.find(':FunctionName:')
                                    if idx != -1:
                                        idx2 = pl.find(':',idx+7)
                                        keyname = pl[idx+7:idx2].strip('"\' ') #DDB keyname
                                        idx = pl.find(',',idx2+1)
                                        key = pl[idx2+1:idx].strip('"\' ') #DDB key
                                    elif idx3 != -1:
                                        #payload:arn:aws:lambda:us-west-2:443592014519:function:FnInvokerPyB:FunctionName:arn:aws:lambda:us-west-2:443592014519:function:DBModPyB:InvocationType:Event:Payload
                                        idx = pl.find(':',idx3+29)
                                        reg = pl[idx3+29:idx]
                                        idx = pl.find(':function:',idx3+29)
                                        idx2 = pl.find(':',idx+10)
                                        tname = pl[idx+10:idx2] #function name
                                        idx = pl.find(':InvocationType:')
                                        idx2 = pl.find(':',idx+16)
                                        keyname= pl[idx+16:idx2] #Event (Async) or RequestResponse (Sync)
                                        key = aws['request_id'] #request ID of invoke call
                                    elif ':TopicArn:arn:aws:sns:' in pl:
                                        idx = pl.find(':TopicArn:arn:aws:sns:')
                                        pl_str = pl[idx+22:].split(':')
                                        reg = pl_str[0]
                                        tname = pl_str[2]#topicARN
                                        keyname = pl_str[4] #Subject
                                        idx = pl.find(':Message:') 
                                        key = pl[idx+9:idx+39] #first 30 chars after Message:
                                    elif ':Bucket:' in pl:
                                        idx = pl.find(':Bucket:')
                                        pl_str = pl[idx+8:].split(':')
                                        tname = pl_str[0] #bucket name
                                        keyname = pl_str[2] #keyname
                                    else:
                                        print('Unhandled GammaRay payload: {}'.format(doc_dict))
                                        assert False
                                if name == 'Initialization':
                                    assert tname == 'unknown' and 'function_arn' in aws
                                    idx = fn.find(':',15)
                                    reg = fn[15:idx] #function's region
                                    idx = fn.find(':function:')
                                    tname = fn[idx+10:] #function name
                                print('\t{} {}:{}:{}:{}:{}:{}:{}:{}'.format(subid,name,op,reg,tname,keyname,key,subs['start_time'],subs['end_time']))
    
                            else:
                                if name == 'requests':
                                    assert 'http' in subs
                                    http = subs['http']
                                    url = http['request']['url'][7:] #trim off the http:// chars
                                    op = http['request']['method']
                                    status = http['response']['status']
                                    print('\t{} {}:{}:{}:{}:{}:{}'.format(subid,name,op,url,status,subs['start_time'],subs['end_time']))
                                else:
                                    print('\t{} UNKNOWN:{}:{}:{}'.format(subid,name,subs['start_time'],subs['end_time']))
                else:
                    pass #can skip this as they are repeats
                    #print(doc_dict)
                    
    print('DONE')
            
   

##################### parseIt #######################
def parseIt(fname,fxray=None):
    global seqID
    if DEBUG:
        print('processing stream {}'.format(fname))
    with open(fname,'r') as f:
        for line in f:
            line = line.strip()
            if line == '':
                continue
            if line.find(' REMOVE:') != -1 and line.endswith(':None'):
                continue
            if line.find(' INSERT:') == -1:
                print('Error: unexpected entry: {}'.format(line))
                sys.exit(1)
            pl = reqID = ts = None
            pl_str = ts_str = reqID_str = ''
            idx = line.find('{')
            pl_str = line[idx:]
            pl_str = pl_str.replace("'",'"')
            pl_str = pl_str.replace('\\\\"','"')
            pl_str = pl_str.replace('\\"','"')
            pl_str = pl_str.replace(' "{"',' {"')
            if DEBUG:
                print(pl_str)
            idx = pl_str.find(', "gr_payload": "pl:')
            if idx != -1: #SDK
                idx2 = pl_str.find(']"}"}"}, "reqID":')
                if idx2 == -1:
                    #{"payload": {"S": {"type": "subsegment", "id": "a8574a50b66e46ed", "trace_id": "1-59d6cd8c-f48a3fa1e6b72ce67f895473", "parent_id": "5f38285778fbea09", "start_time": 1507249552.1728623, "gr_payload": "pl:us-west-2:POST:http://httpbin.org/post", "operation": "HTTP"}"}, "reqID": {"S": "e6bdc994-aa2c-11e7-b3dd-abb9cf5b93ae:d74d3049"}, "ts": {"N": "1507249552173"}}
                    idx2 = pl_str.find('}"}, "reqID":')
                    pltmp = '{}}}'.format(pl_str[idx+20:idx2+3])
                    incr = 5
                else:
                    pltmp = pl_str[idx+20:idx2+2]
                    incr = 8
                pl1 = '{}}}}}}}'.format(pl_str[:idx]) #close up the front section to decode it as json
                pldict = json.loads(pl1)
                pldict = pldict['payload']['S']
                myid = pldict['id']
                pid = pldict['parent_id']
                trid = pldict['trace_id']
                start_ts = float(pldict['start_time'])

                pl1 = '{{{}'.format(pl_str[idx2+incr:]) #extract the backend of the string to get the reqID and ts
                pldict = json.loads(pl1)
                reqidx = pldict['reqID']['S'].rfind(':')
                reqID = pldict['reqID']['S'][:reqidx]
                ts = float(pldict['ts']['N'])
                
                rest_dict = processPayload(pltmp,reqID)
                if not rest_dict:
                    continue
                print('SDK dict: {}'.format(rest_dict))

                #make a child object-- all are possible event sources at this point (B config)
                child = {TYPE:'sdkT',REQ:reqID,SSID:myid,SSPID:pid,TRID:trid,PAYLOAD:rest_dict,TS:start_ts,DUR:0.0,SEQ:seqID,CHILDREN:[]}
                seqID += 1
                assert myid not in SUBSEGS
                SUBSEGS[myid] = child

                _,match = getName(child)
                print('mch: {}'.format(match))
                TRIGGERS[match].append(child)
                #add the SDK as a child to its entry in REQS
                if reqID in REQS:
                    parent = REQS[reqID]
                else: 
                    parent = SUBREQS[reqID]
                parent[CHILDREN].append(child)
                
            else: #entry
                assert pl_str.startswith('{"payload": {"S": "pl:arn:aws:lambda:')
                #entry that was triggered
                idx = pl_str.find('"}}, "reqID":')
                incr = 4
                if idx == -1:
                    idx = pl_str.find('"}, "reqID":')
                    incr = 3
                pl = pl_str[19:idx]
                plrest = '{{{}'.format(pl_str[idx+incr:])
                pldict = json.loads(plrest)
                reqidx = pldict['reqID']['S'].rfind(':')
                reqID = pldict['reqID']['S'][:reqidx]
                ts = float(pldict['ts']['N'])

                #rest = '{{{}'.format(pl_str[idx+4:])
                assert reqID not in REQS
                trigger,payload = processEventSource(pl)
                print('triggered: {}'.format(trigger))
                ele = {TYPE:'fn',REQ:reqID,SSID:'none',SSPID:'none',TRID:'none',PAYLOAD:payload,TS:ts,DUR:0.0,SEQ:seqID,CHILDREN:[]}
                seqID += 1
#HERE CJK what should come back here and what should we store in triggers
                print('(entry) retn: {}'.format(payload))
                if trigger: #this lambda was triggered by an event source
                    _,match = getName(ele)
                    print(match)
                    assert match in TRIGGERS
                    plist = TRIGGERS[match]
                    if len(plist) == 1:
                        parent = plist[0]
                    else:
                        assert False #multiple same events not handled yet
                    parent[CHILDREN].append(ele)
                    SUBREQS[reqID] = ele
                    print('\tadding {} to SUBREQS \n\tparent: {}'.format(ele,parent))
                else: 
                    print('\tadding {} to REQS'.format(reqID))
                    REQS[reqID] = ele

 
##################### main #######################
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='GammaRay Stream Parser')
    parser.add_argument('fname',action='store',help='filename containing stream data')
    parser.add_argument('hybrid',action='store',help='filename containing xray data')
    args = parser.parse_args()

    if not os.path.isfile(args.hybrid) and not os.path.isdir(args.hybrid): 
        parser.print_help()
        print('\nError: hybrid argument must be a file or a directory containing files ending in .xray')
        sys.exit(1)

    processHybrid(args.hybrid)
    parseIt(args.fname, args.hybrid)
    if DEBUG:
        for ele in SDKS:
            print('SDK: ',ele)
    assert SDKS == []
    makeDotAggregate()

