# Component diagram: containment hierarchy

[[[component-decomposition]]]

The "what's inside what" view, from the single `Application` down to one field's widgets. Each
level is a real containment relationship in the code, not just a call:
`Application.show_main_window()` builds exactly one `MainWindow`
(`app.py:55-63`); `DocumentsDock` holds one `DocumentWidget` per open path
(`documents_dock.py:26`); `DocumentWidget` builds a viewer dock and an editor dock from the same
`FieldsForm` (`document_widget.py:38-40`) -- the [[plugins#viewer-editor-both]] surfaces.

```plantuml
@startuml
component "Application (QApplication)" as App
component "ApplicationSingleton" as Singleton
component "MainWindow" as Win
component "DocumentsDock" as Dock

package "one per open path" {
  component "DocumentWidget" as DocW
  component "RehuDocumentModel" as Model
  component "RehuDocument (core)" as Core

  package "built once, shown/hidden independently" {
    component "Viewer dock\n(FieldsForm.make_viewer)" as Viewer
    component "Editor dock\n(FieldsForm.make_editor)" as Editor
  }
}

component "Field / TextField (per field spec)" as FieldC

App *-- Singleton
App *-- Win : show_main_window()
Win *-- Dock
Dock *-- "0..*" DocW : open_document(path)
DocW *-- Model
DocW *-- Viewer
DocW *-- Editor
Model o-- Core : wraps
Viewer ..> FieldC : one row per field
Editor ..> FieldC : one row per field
Viewer ..> Model : field.make_viewer(model.bind(field))
Editor ..> Model : field.make_editors(model.bind(field))
@enduml
```
