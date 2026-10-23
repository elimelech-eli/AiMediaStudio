"""AudioLDM2 hidden-state generation using public GPT-2 forward/cache APIs.

Recent Transformers versions removed generation helpers from GPT2Model. AudioLDM2
needs hidden states, not language-model logits, so an LM-head substitution is wrong.
"""
def generate_hidden_states(self,inputs_embeds,attention_mask=None,max_new_tokens=None,**kwargs):
 import torch
 count=max_new_tokens if max_new_tokens is not None else self.language_model.config.max_new_tokens
 current=inputs_embeds;past=None;generated=[];mask=attention_mask
 for _ in range(count):
  output=self.language_model(inputs_embeds=current,attention_mask=mask,past_key_values=past,use_cache=True,output_hidden_states=True,return_dict=True)
  current=output.hidden_states[-1][:,-1:,:];generated.append(current);past=output.past_key_values
  if mask is not None:mask=torch.cat((mask,torch.ones_like(mask[:,:1])),dim=1)
 return torch.cat(generated,dim=1)
