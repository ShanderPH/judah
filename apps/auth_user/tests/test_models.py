"""Unit tests for the User model."""

import pytest

from apps.auth_user.models import User


@pytest.mark.django_db
class TestUserModel:
    """Tests for the custom User model."""

    def test_create_user_defaults(self) -> None:
        """User created with defaults should have viewer role and not be an AI agent."""
        user = User.objects.create_user(username="testuser", password="Pass1234")
        assert user.role == User.Role.VIEWER
        assert user.is_ai_agent is False
        assert user.is_active is True

    def test_user_str_representation(self) -> None:
        """__str__ should return full name with role."""
        user = User(username="jdoe", first_name="John", last_name="Doe", role="agent")
        assert str(user) == "John Doe (agent)"

    def test_is_admin_property(self) -> None:
        """is_admin should be True only for admin role."""
        admin = User(role=User.Role.ADMIN)
        agent = User(role=User.Role.AGENT)
        assert admin.is_admin is True
        assert agent.is_admin is False

    def test_is_manager_property(self) -> None:
        """is_manager should be True only for manager role."""
        manager = User(role=User.Role.MANAGER)
        viewer = User(role=User.Role.VIEWER)
        assert manager.is_manager is True
        assert viewer.is_manager is False

    def test_is_agent_property(self) -> None:
        """is_agent should be True only for agent role."""
        agent = User(role=User.Role.AGENT)
        admin = User(role=User.Role.ADMIN)
        assert agent.is_agent is True
        assert admin.is_agent is False

    @pytest.mark.django_db
    def test_user_meta_db_table(self) -> None:
        """User model should use the 'users' table."""
        assert User._meta.db_table == "users"

    @pytest.mark.django_db
    def test_unique_username(self) -> None:
        """Creating two users with the same username should raise an error."""
        from django.db import IntegrityError

        User.objects.create_user(username="duplicate", password="Pass1234")
        with pytest.raises(IntegrityError):
            User.objects.create_user(username="duplicate", password="Pass1234")
