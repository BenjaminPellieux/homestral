# HomeStral - Mistral AI for Home Assistant

[![GitHub stars](https://img.shields.io/github/stars/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/issues)
[![License](https://img.shields.io/github/license/BenjaminPellieux/homestral.svg)](https://github.com/BenjaminPellieux/homestral/blob/main/LICENSE)

HomeStral is a powerful integration that brings Mistral AI capabilities to Home Assistant, enabling intelligent voice control and advanced automation for your smart home.


## Features

- **Voice Control**: Use natural language to control your smart home devices
- **AI Conversations**: Leverage Mistral's advanced language models for intelligent responses
- **Speech-to-Text**: Integrates with Voxtral for accurate speech recognition
- **Flexible Configuration**: Choose between Mistral agents or models
- **Customizable**: Adapt the assistant to your specific home automation needs
- **Multi-language Support**: Works with English, French, and more

## Installation

### Prerequisites

- Home Assistant (running in Docker or native)
- Mistral AI API key
- Python 3.9 or higher

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

3. **Restart Home Assistant**

## Configuration

1. Add the integration through the Home Assistant UI:
   - Go to Settings > Devices & Services
   - Click "Add Integration" and search for "HomeStral"

2. Enter your Mistral AI API key when prompted

3. Configure optional settings:
   - Choose between using a Mistral agent or model
   - Set your preferred model (default: mistral-large-latest)
   - Configure agent ID if using an agent
   - Adjust parameters like temperature and max tokens

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

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) for the amazing home automation platform
- [Mistral AI](https://mistral.ai) for the powerful language models
- All contributors who have helped improve this integration

## Support

For questions or support, please open an issue on this repository or contact the maintainer.
