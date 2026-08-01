#!/bin/bash

OUTPUT=env_report.txt

echo "===== SYSTEM =====" > $OUTPUT
hostname >> $OUTPUT
date >> $OUTPUT


echo "===== PYTHON =====" >> $OUTPUT
python --version >> $OUTPUT


echo "===== PYTORCH =====" >> $OUTPUT

python <<EOF >> $OUTPUT
import torch
print(torch.__version__)
EOF


echo "===== TORCH_NPU =====" >> $OUTPUT

python <<EOF >> $OUTPUT
import torch_npu
print(torch_npu.__version__)
EOF


echo "===== NPU =====" >> $OUTPUT

python <<EOF >> $OUTPUT
import torch
print("NPU available:",
      torch.npu.is_available())
EOF


echo "===== VERL =====" >> $OUTPUT

pip show verl >> $OUTPUT


echo "===== VLLM =====" >> $OUTPUT

pip show vllm >> $OUTPUT


echo "===== CANN =====" >> $OUTPUT

cat \
/usr/local/Ascend/ascend-toolkit/latest/version.info \
>> $OUTPUT


echo "Saved:"
echo $OUTPUT