# Sequence diagram: opening a `.rehu` path

[[[sequence-open-document]]]

Traces `packages/rehuco-agent/src/rehuco_agent/__main__.py`'s `main()` through `app.py`'s `run()`
(`app.py:73-94`) down to a new dock appearing, covering both cases `run()` handles: this process
becomes the single-instance primary, or another primary is already running and this process
just forwards its argv and exits ([[nodes#single-instance]]). Builds the [[plugins#dock-shell]]
described in prose.

```plantuml
@startuml
participant "OS / Shell" as OS
participant "__main__.main()" as Main
participant "app.run()" as Run
participant "Application" as App
participant "ApplicationSingleton" as Singleton
participant "MainWindow" as Win
participant "DocumentsDock" as Dock
participant "RehuDocument\n(core)" as Core
participant "RehuDocumentModel" as Model
participant "DocumentWidget" as DocW
participant "FieldsForm" as Form

OS -> Main : exec rehuco-agent a.rehu
Main -> Run : run(argv)
Run -> App : Application(argv)
Run -> Singleton : setup(APP_ID)

alt this process becomes primary
    Singleton --> Run : True
    Run -> Singleton : connect other_instance_run -> open_forwarded
    Run -> App : show_main_window()
    App -> Win : new MainWindow()
    Win -> Dock : new DocumentsDock()
    App --> Run : window
    Run -> App : open_forwarded(argv[1:])

    loop for each path
        App -> Win : open_file(path)
        Win -> Dock : open_document(path)
        alt dock already open for this path
            Dock -> Dock : focus existing dock
        else not yet open
            Dock -> Core : RehuDocument.load(path)
            Dock -> Model : new RehuDocumentModel(document)
            Dock -> DocW : new DocumentWidget(model)
            DocW -> Form : build_document_form()
            DocW -> Form : make_viewer(model), make_editor(model)
            Form -> Model : bind(field) per field
            Dock -> Dock : new CDockWidget, add + focus
        end
    end
    Win -> Win : raise_and_activate()
    Run -> App : app.exec() (event loop)
else another instance is already primary
    Singleton --> Run : False\n(argv already written to the primary's local socket)
    Run --> Main : return 0
    note over Singleton
        On the *other*, already-running process: its ApplicationSingleton
        decodes the forwarded argv and emits other_instance_run(paths),
        re-entering the "for each path" loop above -- no new process,
        no new Application.
    end note
end
@enduml
```
