# Activity diagram: opening one path

The same flow as [sequence-open-document.md](sequence-open-document.md), reframed around its
decision points rather than which object calls which. The fork/join reflects
`DocumentWidget.__init__` (`document_widget.py:38-40`): the viewer and editor forms are both
built, from the same `RehuDocumentModel`, regardless of which dock ends up visible.

## PlantUML

```plantuml
@startuml
start
:receive a path to open;

if (this process is the single-instance primary?) then (no)
    :forward path to the primary\nover the local socket;
    :exit process (return 0);
    stop
else (yes)
endif

:MainWindow.open_file(path);

if (a dock is already open for this path?) then (yes)
    :focus the existing dock;
else (no)
    :RehuDocument.load(path);
    :new RehuDocumentModel(document);
    fork
        :build viewer form (read-only);
    fork again
        :build editor form (writes back through the model);
    end fork
    :wrap both in a new DocumentWidget;
    :add its dock to DocumentsDock's CDockManager, focus it;
endif

:raise_and_activate() the MainWindow;
stop
@enduml
```
