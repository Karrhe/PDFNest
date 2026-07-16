## I. Final Technology Stack

* **Programming language:** Python
* **Recommended supporting technologies:**

  * **PDF rendering engine:** PyMuPDF (`fitz`) for high-performance page rendering and coordinate processing
  * **Desktop GUI framework:** PySide6 or PyQt6 for implementing windows, context menus, and user interaction events
  * **Markdown support:** Use the `markdown` library to convert Markdown into HTML and render it with Qt’s built-in components, or integrate a third-party Markdown editor component

---

## II. Complete Requirements Specification

### 1. Basic PDF Reading Features

* Support opening local PDF files and rendering PDF pages correctly
* Support basic page navigation and zooming
* Automatically adapt the displayed content when the application window is resized

### 2. Note Anchoring and Interaction Logic

* **Right-click interaction:** Right-click anywhere on a PDF page to open a custom context menu containing an **Add Note** option
* **Position anchoring:** Each note must be precisely anchored to the corresponding position on the PDF page where the user right-clicked
* When the page is zoomed or the window size changes, the note anchor must remain aligned with the same location in the original PDF content
* **Visual markers:** Display a visible marker, such as a small colored dot, at each note anchor position
* **Note preview location:** When the user clicks a colored note marker, display the note content in a right-hand sidebar so that it does not obscure the PDF content
* Note editing and management must also be handled in the right-hand sidebar

### 3. Note Content and Formatting

* **Formatting:** Notes must support Markdown syntax, including both editing and rendered preview modes
* **Viewing interaction:** Clicking a note anchor marker on the PDF page must open the corresponding note view and display the rendered Markdown content
* **Editing:** Users must be able to modify and edit existing notes

### 4. Data Storage Rules

* **External and independent storage:** All note data must be stored separately from the original PDF file
* The application must not modify or write data into the original PDF
* **Local persistence:** After closing the application and reopening the same PDF, all previously created notes must be loaded and displayed correctly
* **Anchor storage format:** Store each note anchor using:

  * Page number
  * Normalized coordinates in the range `0.0–1.0`
* The normalized coordinates must represent the relative position within the PDF page, ensuring accurate placement across different zoom levels and window sizes

### 5. Basic Note Management

* Support adding multiple notes at different positions within the same PDF file
* Each note must be managed independently without interfering with other notes
* Support deleting existing notes
