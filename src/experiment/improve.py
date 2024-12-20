import random
from experiment.utils import detect_error, extract_edit_prompt
import torch
import torch.nn as nn

class Improve():
    def __init__(self,
                inferring_reasons, 
                refining_prompts, 
                augumenting_prompts, 
                train_data,
                config,
                request_model):
        self.inferring_reasons = inferring_reasons
        self.refining_prompts = refining_prompts
        self.augumenting_prompts = augumenting_prompts
        self.train_data = train_data
        self.config = config
        self.request = request_model
        self.used_data = []
    
    def evaluate_collect_error(self, prompt, data):
        errors_list = []
        for val in data:
            response = self.request.request(val['input'], prompt)
            if not detect_error(response, val['target']):
                error = {}
                error['input'] = val['input']
                error['output'] = response
                errors_list.append(error)
    
        return errors_list

    def generate_similar_prompt(self, prompt_list):
        similar_prompts = []
        for prompt in prompt_list:
            tmp = self.augumenting_prompts
            content = tmp.replace("$refined_prompt$", prompt)
            for i in range(self.config['addition_sample']):
                response = self.request.request(user=content, system='')
                similar_prompts.append(response)
    
        return similar_prompts

class SimpleLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers=1):
        super(SimpleLSTM, self).__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True) 
        
    def forward(self, x):
        lstm_out, (h_n, c_n) = self.lstm(x)
        return h_n
    
    def load_pretrained_lstm(model_path, input_size, hidden_size):
        model = SimpleLSTM(input_size, hidden_size)
        model.load_state_dict(torch.load(model_path))
        model.eval() 
        return model

    def get_lstm_hidden_state(model, input_data):

        with torch.no_grad():  
            h_n = model(input_data)
        return h_n[-1].squeeze().cpu().numpy()  

    def run(self, prompt, table=None):
        candidate_prompts = []
        batch_data = random.sample(self.train_data, self.config['N_t'])
        self.used_data += batch_data
        errors_list = self.evaluate_collect_error(prompt, batch_data) 
        try:
            errors_group = random.sample(errors_list, self.config['N_e'])
        except:
            errors_group = errors_list
        inferring_reasons = self.inferring_reasons.replace("$prompt$", prompt).replace("$N_r$", str(self.config['N_r'])) 
        refining_prompts = self.refining_prompts.replace("$prompt$", prompt)
        
        for error in errors_group:
            # Inferring reasons for errors
            tmp_prompt = inferring_reasons
            content = tmp_prompt.replace("$error_case$", error['input']) 
            gradient = self.request.request(user=content, system='')

            # Refining prompts with reasons
            tmp_prompt = refining_prompts
            tmp_prompt = tmp_prompt.replace("$error_case$", error['input']) 
            content = tmp_prompt.replace("$reasons$", gradient)
            edit_prompt = self.request.request(user=content, system='')
            edit_prompt_list = extract_edit_prompt(edit_prompt)

            # Augumenting prompts
            similar_prompts = self.generate_similar_prompt(edit_prompt_list)

            # Merge candidate prompts
            candidate_prompts.extend(edit_prompt_list)
            candidate_prompts.extend(similar_prompts)
            
            # add data into wandb Text Table [input, prompt, reason, improved prompt, augumented prompt]
            if self.config['use_wandb']:
                for new_index, new_prompt in enumerate(edit_prompt_list):
                    for mc_index in range(self.config['addition_sample']):
                        table.add_data(error['input'], prompt, gradient, new_prompt, similar_prompts[new_index * self.config['addition_sample'] + mc_index])
        # Randomly sampled #num successor candidates per parent prompt
        try:
            sample_candidate_prompts = random.sample(candidate_prompts, self.config['num_candidates'])
        except:
            sample_candidate_prompts = candidate_prompts
        return sample_candidate_prompts

    def get_used_data(self):
        return self.used_data