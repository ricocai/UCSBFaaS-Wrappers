#! /bin/bash
if [ -z ${1+x} ]; then echo 'Unset AWS profile name. Set and rerun. Exiting...!'; exit 1; fi
if [ -z ${2+x} ]; then echo 'Unset count (second var). Set and rerun. Exiting...!'; exit 1; fi
if [ -z ${3+x} ]; then echo 'Unset prefix as arg3 (full path to/including UCSBFaaS-Wrappers). Set and rerun. Exiting...!'; exit 1; fi
PROF=$1
COUNT=$2
PREFIX=$3
LAMDIR=${PREFIX}/lambda-python
GRDIR=${PREFIX}/gammaRay
CWDIR=${PREFIX}/tools/cloudwatch
TOOLSDIR=${PREFIX}/tools/timings
SPOTTABLE=spotFns #must match tablename used by SpotWrap.py.template
TS=1401861965497 #some early date
REG=us-west-2

S3TESTBKT=cjk-spotwraptest0831
FILELIST=( 
    s3setupB emptyB dbreadB dbsetupB dbwriteB s3readB s3writeB pubsnsB  \
    s3setupC emptyC dbreadC dbsetupC dbwriteC s3readC s3writeC pubsnsC \
    s3setupF emptyF dbreadF dbsetupF dbwriteF s3readF s3writeF pubsnsF \
    s3setupS emptyS dbreadS dbsetupS dbwriteS s3readS s3writeS pubsnsS \
    s3setupT emptyT dbreadT dbsetupT dbwriteT s3readT s3writeT pubsnsT  \
    s3setupD emptyD dbreadD dbsetupD dbwriteD s3readD s3writeD pubsnsD \
)
FILELIST=( 
    s3setupF emptyF dbreadF dbsetupF dbwriteF s3readF s3writeF pubsnsF \
    s3setupB emptyB dbreadB dbsetupB dbwriteB s3readB s3writeB pubsnsB  \
)

cd ${GRDIR}
. ./venv/bin/activate
cd ${CWDIR}
	
for f in "${FILELIST[@]}"
do
    echo "processing: ${f}"
    #cleanup
    if [[ $f == s3write* ]] ;
    then
        aws s3 rm s3://${S3TESTBKT}/write --recursive --profile ${PROF}
    fi
    python downloadLogs.py "/aws/lambda/${f}" ${TS} -p ${PROF} --deleteOnly
    for i in `seq 1 ${COUNT}`;
    do
        aws lambda invoke --invocation-type Event --function-name ${f} --region ${REG} --profile ${PROF} --payload "{}" outputfile
        /bin/sleep 30 #seconds
        mkdir -p $i/APIS/
        python downloadLogs.py "/aws/lambda/${f}" ${TS} -p ${PROF} > $i/APIS/${f}.log
    done
done
aws s3 rm s3://${S3TESTBKT}/write --recursive --profile ${PROF}
deactivate
