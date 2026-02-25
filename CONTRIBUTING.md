# Contributing to TokioAI

Thank you for your interest in contributing to TokioAI! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Respect different viewpoints and experiences

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported
2. Use the bug report template
3. Include:
   - Clear description of the issue
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, etc.)
   - Relevant logs or error messages

### Suggesting Features

1. Check if the feature has already been suggested
2. Use the feature request template
3. Include:
   - Clear description of the feature
   - Use cases and benefits
   - Possible implementation approach (if known)

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make your changes**
   - Follow code style guidelines
   - Write/update tests
   - Update documentation

4. **Commit your changes**
   ```bash
   git commit -m "Add amazing feature"
   ```
   - Use clear, descriptive commit messages
   - Reference issues when applicable

5. **Push to your fork**
   ```bash
   git push origin feature/amazing-feature
   ```

6. **Open a Pull Request**
   - Use the PR template
   - Describe your changes clearly
   - Link related issues

## Development Setup

See [README.md](README.md) for setup instructions.

## Code Style

### Python

- Follow PEP 8
- Use type hints where possible
- Maximum line length: 100 characters
- Use `black` for formatting:
  ```bash
  black tokio-ai/
  ```

### TypeScript/JavaScript

- Follow ESLint rules
- Use Prettier for formatting:
  ```bash
  npm run format
  ```

### Documentation

- Use docstrings for all functions/classes
- Follow Google-style docstrings
- Update README.md for user-facing changes
- Update docs/ for architectural changes

## Testing

- Write tests for new features
- Ensure all tests pass:
  ```bash
  pytest tests/
  ```
- Maintain or improve test coverage

## Security

- Never commit secrets or credentials
- Report security issues privately to security@tokioia.com
- Follow security best practices in code

## Review Process

1. All PRs require at least one approval
2. Maintainers will review within 48 hours
3. Address feedback promptly
4. Keep PRs focused and small when possible

## Questions?

- Open a discussion on GitHub
- Check existing documentation
- Ask in issues (tag as "question")

Thank you for contributing! 🎉
