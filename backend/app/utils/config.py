from app.utils.config_loader import ConfigLoader
from app.utils.path_tool import get_abstract_path

chroma_config = ConfigLoader.load_yaml(config_path=get_abstract_path('app/config/chroma.yaml'))
prompt_config = ConfigLoader.load_yaml(config_path=get_abstract_path('app/config/prompt.yaml'))
agent_config = ConfigLoader.load_yaml(config_path=get_abstract_path('app/config/agent.yaml'))

if __name__ == '__main__':
    print(chroma_config)
    print(prompt_config)
    print(agent_config)