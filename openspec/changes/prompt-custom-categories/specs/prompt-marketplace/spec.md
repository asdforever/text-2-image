## Purpose

为提示词商城提供可维护的业务分类体系，让团队能够按商品阶段、用途或内部约定组织提示词，同时保留现有按执行类型区分提示词的能力。

## ADDED Requirements

### Requirement: Custom categories are persistent resources

The system SHALL allow an authorized marketplace user to create, list, rename, and delete custom prompt categories. Each category MUST have a stable identifier and a trimmed, non-empty name that is unique case-insensitively.

#### Scenario: Create a category
- **WHEN** the user submits a new category name that is not blank and does not duplicate an existing name
- **THEN** the system persists the category and returns its stable identifier and name

#### Scenario: Reject an invalid category name
- **WHEN** the user submits a blank name or a name that duplicates an existing category ignoring case and surrounding whitespace
- **THEN** the system rejects the request with a field-level validation error and does not create a category

#### Scenario: Rename a category
- **WHEN** the user changes a category name to a valid unused name
- **THEN** the system updates the category name without changing its identifier or the templates assigned to it

#### Scenario: Delete a category with assigned templates
- **WHEN** the user confirms deletion of a category that has assigned templates
- **THEN** the system deletes the category, moves those templates to the uncategorized state, and does not delete or alter their prompt content or versions

### Requirement: Prompt templates can be assigned to a business category

The system SHALL allow a prompt template to have zero or one custom business category, independently of its execution type. Template creation and template metadata updates MUST accept a category selection, and omitted or cleared selection MUST mean uncategorized.

#### Scenario: Create a categorized template
- **WHEN** the user creates a prompt template and selects an existing category
- **THEN** the template response includes that category identifier and name, and the association is visible after reloading the marketplace

#### Scenario: Create an uncategorized template
- **WHEN** the user creates a prompt template without selecting a category
- **THEN** the template is listed under “未分类” and remains available through the existing execution-type grouping

#### Scenario: Change a template category
- **WHEN** the user edits a template and selects a different category or clears the selection
- **THEN** the system updates only the category association and preserves the template code, execution type, versions, and prompt content

### Requirement: Marketplace supports category browsing and management

The system SHALL show category filters alongside existing execution-type groups, including “全部” and “未分类”, and SHALL show the number of templates in each category. Selecting a category MUST limit the result grid, sidebar list, and batch-selection actions to templates in that category; text search MUST continue to apply within the selected category.

#### Scenario: Browse a custom category
- **WHEN** the user selects a custom category in the marketplace sidebar
- **THEN** the grid and list show only templates assigned to that category and the active category is visually indicated

#### Scenario: Browse uncategorized templates
- **WHEN** the user selects “未分类”
- **THEN** the marketplace shows templates whose category association is empty, without hiding templates based on execution type

#### Scenario: Manage categories from the marketplace
- **WHEN** the user opens category management
- **THEN** the user can create, rename, or delete a category, sees affected-template counts before deletion, and sees the current filter refresh without losing unrelated template selection

#### Scenario: Category has no matching templates
- **WHEN** the user selects a category with zero assigned templates
- **THEN** the marketplace shows an empty state that identifies the category and offers a direct action to create a prompt or return to all templates

### Requirement: Existing prompt marketplace behavior remains compatible

The system SHALL preserve existing execution-type labels, template version operations, deletion behavior, search behavior, and legacy templates that have no category data. Existing templates MUST be readable and editable after the category feature is deployed.

#### Scenario: Read a legacy template
- **WHEN** the marketplace loads a template created before custom categories existed
- **THEN** it renders the template as uncategorized and all existing actions remain available

#### Scenario: Filter and search together
- **WHEN** the user selects a category and enters a search query
- **THEN** the result contains only templates matching both the category and the existing name/code/type search semantics
