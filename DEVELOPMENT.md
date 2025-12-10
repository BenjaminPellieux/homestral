# Development Guide for HomeStral

## Overview
This guide provides technical details about the HomeStral project, including its architecture, modules, and data flows.

## Architecture

### High-Level Architecture
HomeStral is a Home Assistant integration that leverages Mistral AI for voice control and intelligent automation. The architecture consists of the following main components:

1. **STT (Speech-to-Text)**: Handles audio processing and transcription using the Voxtral API.
2. **Conversation**: Manages conversations with users and interactions with the Mistral API.
3. **Sensor**: Provides sensor entities for Home Assistant.
4. **Config Flow**: Handles the configuration flow for the integration.
5. **Services**: Exposes services for generating content and interacting with the integration.

### Data Flow

#### STT Data Flow
1. **Audio Input**: Audio data is captured from the user's microphone.
2. **Audio Processing**: The audio data is processed and converted to the required format (WAV, PCM, 16kHz, 16-bit, mono).
3. **API Call**: The processed audio is sent to the Voxtral API for transcription.
4. **Transcription**: The transcribed text is returned and used for further processing.

#### Conversation Data Flow
1. **User Input**: The user provides input via voice or text.
2. **Conversation Start**: A new conversation is started with the Mistral API.
3. **API Call**: The user input is sent to the Mistral API for processing.
4. **Response Handling**: The response from the API is parsed and formatted.
5. **Conversation Continue**: The conversation is continued with additional user inputs.

## Modules

### `stt.py`
This module handles speech-to-text functionality using the Voxtral API. It includes:
- Audio processing and format conversion.
- API calls to the Voxtral service for transcription.
- Error handling and logging.

### `conversation.py`
This module manages conversations with users and interactions with the Mistral API. It includes:
- Starting and continuing conversations.
- Handling user inputs and API responses.
- Error handling and logging.

### `sensor.py`
This module provides sensor entities for Home Assistant. It includes:
- Sensor configuration and setup.
- Sensor data management.

### `config_flow.py`
This module handles the configuration flow for the integration. It includes:
- User input validation.
- Configuration setup and management.

### `services.yaml`
This file defines the services exposed by the integration. It includes:
- Service definitions and configurations.
- Input validation and examples.

## Development Setup

### Prerequisites
- Python 3.9 or higher
- Home Assistant (running in Docker or native)
- Mistral AI API key

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/BenjaminPellieux/homestral.git
   ```
2. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the integration to your Home Assistant configuration:
   ```bash
   cp -r homestral /path/to/homeassistant/config/custom_components/
   ```
4. Restart Home Assistant.

### Running Tests
To run the tests, use the following command:
```bash
pytest tests/
```

### Contributing
We welcome contributions! Please follow these steps:

1. Fork the repository.
2. Create your feature branch:
   ```bash
   git checkout -b feature/AmazingFeature
   ```
3. Commit your changes:
   ```bash
   git commit -m 'Add some AmazingFeature'
   ```
4. Push to the branch:
   ```bash
   git push origin feature/AmazingFeature
   ```
5. Open a Pull Request.

## Error Handling

### Custom Exceptions
HomeStral uses custom exceptions for error handling. The main exceptions are defined in `errors.py`:

- `HomestralError`: Base class for all HomeStral errors.
- `APIError`: Errors related to the Mistral API.
- `ConfigurationError`: Errors related to configuration.
- `AudioProcessingError`: Errors related to audio processing.
- `ConversationError`: Errors related to conversation management.

### Logging
HomeStral uses structured logging for better error tracking and debugging. The logging configuration is defined in `logging_config.py`:

- **JSON Formatter**: Logs are formatted in JSON for easy parsing and analysis.
- **Log Levels**: Logs can be configured to different levels (DEBUG, INFO, WARNING, ERROR).

## Best Practices

### Code Style
- Follow PEP 8 guidelines for Python code.
- Use descriptive variable and function names.
- Include docstrings for all public functions and classes.

### Testing
- Write unit tests for all new features.
- Write integration tests for critical paths.
- Ensure all tests pass before submitting a Pull Request.

### Documentation
- Update the documentation for any new features or changes.
- Include examples and use cases in the documentation.

## Support

For questions or support, please open an issue on this repository or contact the maintainer.