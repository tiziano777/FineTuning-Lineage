"""Custom error types for Streamlit UI layer."""

from __future__ import annotations

class UIError(Exception):
    """Base error for UI layer with user-friendly and technical messages."""

    def __init__(self, user_message: str, details: str = ""):
        """Initialize UIError.

        Args:
            user_message: User-friendly error message for UI display.
            details: Technical details for logging/debugging.
        """
        self.user_message = user_message
        self.details = details
        super().__init__(user_message)

    def __str__(self) -> str:
        """Return user-friendly message."""
        return self.user_message

class ValidationError(UIError):
    """Validation error with field-level details."""

    def __init__(self, field_name: str, message: str, details: str = ""):
        """Initialize ValidationError.

        Args:
            field_name: Field that failed validation.
            message: Error message.
            details: Technical details.
        """
        self.field_name = field_name
        super().__init__(f"{field_name}: {message}", details)

class APIError(UIError):
    """API error with HTTP status code."""

    def __init__(self, status_code: int, message: str, details: str = ""):
        """Initialize APIError.

        Args:
            status_code: HTTP status code.
            message: Error message.
            details: Technical details.
        """
        self.status_code = status_code
        super().__init__(f"API Error {status_code}: {message}", details)

class ConnectionError(UIError):
    """Connection error for Neo4j/API connectivity issues."""

    pass

class DeleteProtectionError(UIError):
    """Error raised when attempting to delete a node with dependencies."""

    def __init__(self, node_name: str, dependency_count: int, dependency_type: str):
        """Initialize DeleteProtectionError.

        Args:
            node_name: Name of the node being deleted.
            dependency_count: Number of dependent nodes/relationships.
            dependency_type: Description of the dependency type.
        """
        user_msg = (
            f"Cannot delete {node_name}: "
            f"{dependency_count} {dependency_type}(s) depend on it. "
            f"Delete those first."
        )
        self.node_name = node_name
        self.dependency_count = dependency_count
        self.dependency_type = dependency_type
        super().__init__(user_msg)

class DuplicateRecipeError(UIError):
    """Recipe with this name already exists.

    Provides user message, details, and suggested recovery options.
    """

    def __init__(self, recipe_name: str, recovery_suggestions: list[str] | None = None):
        """Initialize DuplicateRecipeError.

        Args:
            recipe_name: Name of recipe that already exists.
            recovery_suggestions: List of alternative names to try (optional).
        """
        self.recipe_name = recipe_name
        self.recovery_suggestions = recovery_suggestions or []

        suggestions_text = ""
        if self.recovery_suggestions:
            suggestions_text = "\n\nSuggested alternatives:\n"
            for i, alt in enumerate(self.recovery_suggestions[:3], 1):  # Show top 3
                suggestions_text += f"  {i}. {alt}\n"

        super().__init__(
            user_message=f"⚠️ Recipe '{recipe_name}' already exists",
            details=f"Choose a different recipe name or upload with a different filename.{suggestions_text}"
        )
