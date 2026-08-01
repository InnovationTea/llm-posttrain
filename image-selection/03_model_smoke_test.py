import torch
from transformers import AutoModelForCausalLM


MODEL="your_model_path"


model=AutoModelForCausalLM.from_pretrained(
    MODEL,
    torch_dtype=torch.bfloat16
)


model=model.to("npu")


inputs={
    "input_ids":
    torch.ones(
        1,
        32,
        dtype=torch.long
    ).npu()
}


with torch.no_grad():

    out=model(**inputs)


print(
    "forward PASS"
)