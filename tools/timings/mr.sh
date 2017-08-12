#! /bin/bash
if [ -z ${1+x} ]; then echo 'Unset args. Set and rerun. Exiting...!'; exit 1; fi
PROF=$1
MRBKT=spot-mr-bkt #must match reducerCoordinator "permission" in setupconfig.json when setupApps.py is run without --no_spotwrap
MRBKTNS=spot-mr-bkt-ns #must match reducerCoordinator "permission" in setupconfig.json when setupApps.py is run with --no_spotwrap
JOBID=job4000  #must match reducerCoordinator "job_id" in setupconfig.json when setupApps.py is run without --no_spotwrap
JOBIDNS=jobNS4000 #must match reducerCoordinator "job_id" in setupconfig.json when setupApps.py is run with --no_spotwrap
PREFIX=/Users/ckrintz/RESEARCH/lambda/UCSBFaaS-Wrappers
LAMDIR=${PREFIX}/lambda-python
DYNDBDIR=${PREFIX}/tools/dynamodb
CWDIR=${PREFIX}/tools/cloudwatch
TOOLSDIR=${PREFIX}/tools/timings
MRDIR=${PREFIX}/lambda-python/mr
SPOTTABLE=spotFns #must match tablename used by SpotWrap.py.template
TS=1401861965497 #some early date

#delete db entries
cd ${DYNDBDIR}
. ./venv/bin/activate
python dynamodelete.py -p ${PROF} ${SPOTTABLE}
deactivate
#delete the logs
cd ${LAMDIR}
. ./venv/bin/activate
cd ${CWDIR}
python downloadLogs.py "/aws/lambda/mapper" ${TS} -p ${PROF} --deleteOnly
python downloadLogs.py "/aws/lambda/reducer" ${TS} -p ${PROF} --deleteOnly
python downloadLogs.py "/aws/lambda/driver" ${TS} -p ${PROF} --deleteOnly
python downloadLogs.py "/aws/lambda/reducerCoordinator" ${TS} -p ${PROF} --deleteOnly
deactivate

for i in `seq 1 1`;
do
    #delete the bucket contents for the job
    aws s3 rm s3://${MRBKT}/${JOBID} --recursive --profile ${PROF}

    cd ${MRDIR}
    . ../venv/bin/activate
    #run the driver
    aws lambda invoke --invocation-type Event --function-name driver --region us-west-2 --profile ${PROF} --payload "{\"eventSource\":\"ext:invokeCLI\",\"prefix\":\"pavlo/text/1node/uservisits/\",\"job_id\":\"${JOBID}\",\"mapper\":\"mapper\",\"reducer\":\"reducer\",\"bucket\":\"big-data-benchmark\",\"jobBucket\":\"${MRBKT}\",\"region\":\"us-west-2\",\"full_async\":\"yes\"}" outputfile
    /bin/sleep 900 #seconds, so 15mins

    #download cloudwatch logs (and delete them)
    cd ${CWDIR}
    mkdir -p $i/MR
    python downloadLogs.py "/aws/lambda/mapper" ${TS} -p ${PROF}  > $i/MR/map.log
    python downloadLogs.py "/aws/lambda/reducer" ${TS} -p ${PROF} > $i/MR/red.log
    python downloadLogs.py "/aws/lambda/driver" ${TS} -p ${PROF}  > $i/MR/driv.log
    python downloadLogs.py "/aws/lambda/reducerCoordinator" ${TS} -p ${PROF} > $i/MR/coord.log
    #python downloadLogs.py "/aws/lambda/mapper" ${TS} -p ${PROF} --delete  > $i/MR/map.log
    #python downloadLogs.py "/aws/lambda/reducer" ${TS} -p ${PROF} --delete > $i/MR/red.log
    #python downloadLogs.py "/aws/lambda/driver" ${TS} -p ${PROF} --delete  > $i/MR/driv.log
    #python downloadLogs.py "/aws/lambda/reducerCoordinator" ${TS} -p ${PROF} --delete > $i/MR/coord.log
    deactivate
    
    #download the db and then delete its entries
    #cd ${DYNDBDIR}
    #. ./venv/bin/activate
    #rm -rf dump
    #python dynamodump.py -m backup -r us-west-2 -p ${PROF} -s ${SPOTTABLE}
    #mkdir -p $i/MR
    #rm -rf $i/MR/*
    #mv dump $i/MR/
    #python dynamodelete.py -p ${PROF} ${SPOTTABLE}
    #deactivate
done

