from django import forms
from django.utils import timezone
from .models import (
    Task, TaskAttachment, TaskReminder, TaskTag, TaskComment,
    Project, ProjectTag, ProjectAttachment, TimeEntry, CustomField, CustomFieldValue
)
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.db.models import Q

User = get_user_model()

class DatePickerInput(forms.DateTimeInput):
    """Custom DateTimeInput widget with HTML5 date picker."""
    input_type = 'datetime-local'

class ProjectForm(forms.ModelForm):
    """Form for creating and updating projects."""
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Project start date (optional)"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Project end date (optional, must be after start date)"
    )
    status = forms.ChoiceField(
        choices=Project.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='active',
        help_text="Project status"
    )
    tags = forms.ModelMultipleChoiceField(
        queryset=ProjectTag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'select2 form-control'}),
        help_text="Add tags/labels for this project"
    )
    color = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color', 'style': 'width: 3rem; padding: 0;'}),
        help_text="Pick a color for this project (optional)"
    )
    icon = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 🚀 or fa-project-diagram'}),
        help_text="Icon or emoji for this project (optional)"
    )
    attachments = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'multiple': True, 'class': 'form-control'}),
        help_text="Attach files (optional)",
    )
    invite_emails = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Invite team by email, comma-separated'}),
        help_text="Invite team members by email (comma-separated)"
    )
    class Meta:
        model = Project
        fields = ['name', 'description', 'members', 'start_date', 'end_date', 'status', 'tags', 'color', 'icon']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'members': forms.SelectMultiple(attrs={'class': 'select2 form-control'}),
        }
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.instance.owner = user
            self.fields['members'].queryset = User.objects.filter(is_active=True)
            self.fields['tags'].queryset = ProjectTag.objects.filter(created_by=user)
    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', "End date must be after start date.")
        # Unique project name for this user
        name = cleaned.get('name')
        if name and Project.objects.filter(name=name, owner=self.instance.owner).exclude(pk=self.instance.pk).exists():
            self.add_error('name', "You already have a project with this name.")
        return cleaned

class TaskForm(forms.ModelForm):
    """Form for creating and updating tasks."""
    
    # Add a field for selecting tags with a more friendly UI
    tags = forms.ModelMultipleChoiceField(
        queryset=TaskTag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'select2 form-control'}),
        help_text=_("Select one or more tags for this task")
    )
    
    # Make the due date field use the date picker
    due_date = forms.DateTimeField(
        required=False,
        widget=DatePickerInput(attrs={'class': 'form-control'}),
        help_text=_("When is this task due?")
    )
    
    # Add estimated hours field
    estimated_hours = forms.DecimalField(
        required=False,
        min_value=0.01,
        max_value=999.99,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.25'}),
        help_text=_("Estimated hours to complete (e.g., 2.5)")
    )
    
    # Add fields for selecting project and dependencies
    project = forms.ModelChoiceField(
        queryset=Project.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_("Select a project for this task (optional)")
    )
    
    parent_task = forms.ModelChoiceField(
        queryset=Task.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_("Select a parent task if this is a subtask")
    )
    
    dependencies = forms.ModelMultipleChoiceField(
        queryset=Task.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'select2 form-control'}),
        help_text=_("Select tasks that must be completed before this one")
    )
    
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'priority', 'status',
            'due_date', 'assignees', 'tags', 'project',
            'parent_task', 'dependencies', 'estimated_hours'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'assignees': forms.SelectMultiple(attrs={'class': 'select2 form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # If we have a user
        if user:
            # Set available projects
            self.fields['project'].queryset = Project.objects.filter(
                Q(owner=user) | Q(members=user)
            ).distinct()
            
            # Set available parent tasks and dependencies
            # Only show tasks owned by or assigned to the user
            available_tasks = Task.objects.filter(
                Q(owner=user) | Q(assignees=user)
            ).exclude(status__in=['completed', 'archived'])
            
            # For editing, exclude the current task from parent_task options
            if self.instance.pk:
                available_tasks = available_tasks.exclude(pk=self.instance.pk)
                
                # Fetch current dependencies to avoid dependency cycles
                dependencies = self.instance.dependencies.all()
                dependent_tasks = self.instance.dependent_tasks.all()
                
                # Exclude tasks that would create a dependency cycle
                cycle_tasks = [self.instance.pk]
                cycle_tasks.extend([t.pk for t in dependent_tasks])
                self.fields['dependencies'].queryset = available_tasks.exclude(
                    pk__in=cycle_tasks
                )
            else:
                self.fields['dependencies'].queryset = available_tasks
                
            self.fields['parent_task'].queryset = available_tasks
            
            # Show only tags created by the user or already associated with the task
            self.fields['tags'].queryset = TaskTag.objects.filter(created_by=user)
            
            # Filter assignees to active users
            self.fields['assignees'].queryset = User.objects.filter(is_active=True)
    
    def clean_dependencies(self):
        dependencies = self.cleaned_data.get('dependencies')
        if self.instance.pk and dependencies:
            # Check for dependency cycles
            for dependency in dependencies:
                if self.instance.has_dependency_cycle(dependency.pk):
                    raise forms.ValidationError(
                        f"Adding '{dependency.title}' as a dependency would create a cycle."
                    )
        return dependencies
    
    def clean_due_date(self):
        due_date = self.cleaned_data.get('due_date')
        if due_date and due_date < timezone.now():
            raise forms.ValidationError("Due date cannot be in the past.")
        return due_date
    
    def clean_estimated_hours(self):
        estimated_hours = self.cleaned_data.get('estimated_hours')
        if estimated_hours is not None and estimated_hours <= 0:
            raise forms.ValidationError("Estimated hours must be greater than zero.")
        return estimated_hours

class TaskAttachmentForm(forms.ModelForm):
    class Meta:
        model = TaskAttachment
        fields = ['file']
    
    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if task:
            self.instance.task = task
        if user:
            self.instance.uploaded_by = user
    
    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Set file metadata
            self.instance.file_name = file.name
            self.instance.file_type = file.content_type
            self.instance.file_size = file.size
            
            # Validate file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError("File size cannot exceed 10MB.")
        return file


class TaskReminderForm(forms.ModelForm):
    class Meta:
        model = TaskReminder
        fields = ['reminder_time', 'reminder_type']
        widgets = {
            'reminder_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
    
    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if task:
            self.instance.task = task
        if user:
            self.instance.created_by = user
    
    def clean_reminder_time(self):
        reminder_time = self.cleaned_data.get('reminder_time')
        if reminder_time and reminder_time < timezone.now():
            raise forms.ValidationError("Reminder time cannot be in the past.")
        return reminder_time


class TaskTagForm(forms.ModelForm):
    class Meta:
        model = TaskTag
        fields = ['name', 'color']
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            self.instance.created_by = user


class TaskCommentForm(forms.ModelForm):
    """Form for adding comments to tasks."""
    
    class Meta:
        model = TaskComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('Add a comment...')
            }),
        }
        labels = {
            'content': _(''),
        }
    
    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if task:
            self.instance.task = task
        if user:
            self.instance.user = user


class TaskSearchForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'placeholder': 'Search tasks...',
        'class': 'search-input'
    }))
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Status')] + list(Task.STATUS_CHOICES),
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    priority = forms.ChoiceField(
        required=False,
        choices=[('', 'All Priorities')] + list(Task.PRIORITY_CHOICES),
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    due_date = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Any Date'),
            ('today', 'Due Today'),
            ('tomorrow', 'Due Tomorrow'),
            ('week', 'Due This Week'),
            ('month', 'Due This Month'),
            ('overdue', 'Overdue'),
            ('none', 'No Due Date'),
        ],
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    created_date = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Any Creation Date'),
            ('today', 'Created Today'),
            ('yesterday', 'Created Yesterday'),
            ('week', 'Created This Week'),
            ('month', 'Created This Month'),
        ],
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    assignee = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.filter(is_active=True),
        empty_label="Any Assignee",
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    created_by = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.filter(is_active=True),
        empty_label="Created By Anyone",
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    tags = forms.ModelMultipleChoiceField(
        required=False,
        queryset=TaskTag.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'select2-multiple'})
    )
    is_ai_generated = forms.BooleanField(required=False)
    has_attachments = forms.BooleanField(required=False)
    has_comments = forms.BooleanField(required=False)
    project = forms.ModelChoiceField(
        required=False,
        queryset=Project.objects.all(),
        empty_label="Any Project",
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    estimated_hours_min = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Min Hours'})
    )
    estimated_hours_max = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Max Hours'})
    )
    is_subtask = forms.BooleanField(required=False)
    search_in = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('title', 'Title'),
            ('description', 'Description'),
            ('comments', 'Comments'),
        ],
        initial=['title', 'description'],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ('-created_at', 'Newest First'),
            ('created_at', 'Oldest First'),
            ('due_date', 'Due Date (ascending)'),
            ('-due_date', 'Due Date (descending)'),
            ('priority', 'Priority (low to high)'),
            ('-priority', 'Priority (high to low)'),
            ('title', 'Title (A-Z)'),
            ('-title', 'Title (Z-A)'),
        ],
        initial='-created_at',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

class TimeEntryForm(forms.ModelForm):
    """Form for creating and updating time entries."""
    
    class Meta:
        model = TimeEntry
        fields = ['description', 'start_time', 'end_time', 'is_billable']
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'is_billable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if task:
            self.instance.task = task
        if user:
            self.instance.user = user
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError("End time must be after start time")
            
        return cleaned_data 