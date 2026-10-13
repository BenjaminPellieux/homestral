# HomeStral - Mistral AI for Home Assistant

[![GitHub stars](https://img.shields.io/github/stars/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/issues)
[![License](https://img.shields.io/github/license/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/blob/main/LICENSE)

HomeStral is a powerful integration that brings Mistral AI capabilities to Home Assistant, enabling intelligent voice control and advanced automation for your smart home.


## Features

- **Mistral Large 4 Chat**: Powered by Mistral's flagship multimodal model with a 1M context window
- **Voice-Driven Device Control**: Control your smart home devices with natural language through tool calling (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`)
- **Voxtral 2 Speech-to-Text**: Accurate speech recognition with home-automation context biasing, supporting 13 languages
- **Voxtral Text-to-Speech**: Natural voice responses synthesized with Voxtral TTS
- **Selectable Models**: Choose between Mistral Large, Medium, and Small in the config flow
- **Configurable Tool Loop**: Bound the number of tool-call iterations per conversation turn (`max_tool_iterations`, default 5)
- **Direct Voice Queries**: Ask Homestral directly ("Demande à Homestral ...") through the `HomestralQuery` intent and shipped custom sentences
- **Customizable**: Adapt the assistant to your specific home automation needs
- **Multi-language Support**: Works with English, French, and more

## Installation

### Prerequisites

- Home Assistant 2025.11 or higher (requires Python 3.13+)
- Mistral AI API key (`MISTRAL_API_KEY`) with access to the `mistral-large` and `voxtral` models

### Installation Steps

1. **Add this repository to HACS** (recommended):
   - Go to HACS in Home Assistant
   - Add this repository URL: `https://github.com/BenjaminPellieux/homestral`
   - Install the "HomeStral" integration

2. **Or manual installation**:
   ```bash
   git clone https://github.com/BenjaminPellieux/homestral.git
   cp -r homestral /path/to/homeassistant/config/custom_components/
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Restart Home Assistant**

## Configuration

1. Add the integration through the Home Assistant UI:
   - Go to Settings > Devices & Services
   - Click "Add Integration" and search for "HomeStral"

2. Enter your Mistral AI API key when prompted

3. Configure optional settings:
   - Choose between using a Mistral agent or model
   - Select your chat model (default: `mistral-large-latest`):
     - `mistral-large-latest` — Mistral Large 4 (flagship, multimodal, 1M context)
     - `mistral-large-4` — Mistral Large 4 (pinned preview ID)
     - `mistral-medium-latest` — Mistral Medium 3.5
     - `mistral-small-latest` — Mistral Small 4
   - Configure agent ID if using an agent
   - Set the maximum tool-call iterations per turn (`max_tool_iterations`, default: 5, range: 1–10)
   - Adjust parameters like temperature and max tokens

Speech-to-text uses Voxtral 2 (Voxtral Mini Transcribe 2) and text-to-speech uses Voxtral TTS (`voxtral-mini-tts-2603`); both are set up automatically with your Mistral AI API key.

## Usage Examples

### Basic Voice Commands

- "Turn on the living room lights"
- "What's the temperature in the bedroom?"
- "Set the thermostat to 22 degrees"
- "What's on my to-do list?"

### Advanced Conversations

- "Why is my energy usage higher than usual?"
- "Can you suggest ways to optimize my smart home setup?"
- "What's the weather forecast for tomorrow?"

### Direct Voice Queries (HomestralQuery Intent)

Homestral ships a `HomestralQuery` intent so you can talk to it directly:

- "Demande à Homestral quelle est la météo"
- "Ask Homestral what the weather is"

The free text is forwarded to the Mistral conversation, which can control your devices through tool calling, and the answer is spoken back.

To enable it, copy the shipped custom sentences into your Home Assistant configuration:

```bash
mkdir -p /path/to/homeassistant/config/custom_sentences/fr /path/to/homeassistant/config/custom_sentences/en
cp custom_sentences/fr.yaml /path/to/homeassistant/config/custom_sentences/fr/homestral.yaml
cp custom_sentences/en.yaml /path/to/homeassistant/config/custom_sentences/en/homestral.yaml
```

Then restart Home Assistant (or reload the conversation integration). The sentences capture the free text in the `{query}` wildcard slot.

## Customization

### Configuration Options

You can customize the integration through the `configuration.yaml` file:

```yaml
homestral:
  api_key: "your-mistral-api-key"
  use_agent: false
  agent_id: "your-agent-id"
  model: "mistral-large-latest"
```

### Custom Commands

Create custom commands by extending the integration:

```python
# In your custom component
def async_handle_message(self, user_input, chat_log):
    if "custom command" in user_input.text.lower():
        # Handle your custom command
        return custom_response
```

## Troubleshooting

### Common Issues

1. **API Connection Errors**:
   - Verify your API key is correct
   - Check your internet connection
   - Ensure Mistral AI service is available

2. **Audio Recognition Problems**:
   - Make sure your microphone is properly configured
   - Speak clearly and avoid background noise
   - Check audio format is supported (16kHz, 16-bit PCM)

3. **Integration Not Showing**:
   - Verify the custom component is in the correct directory
   - Check Home Assistant logs for errors
   - Restart Home Assistant after installation

## Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Running Tests

To run the tests, use the following command:

```bash
pytest tests/
```

### Development Guide

For more details on the architecture, modules, and data flows, please refer to the [Development Guide](DEVELOPMENT.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) for the amazing home automation platform
- [Mistral AI](https://mistral.ai) for the powerful language models
- All contributors who have helped improve this integration

## Support

For questions or support, please open an issue on this repository or contact the maintainer.
