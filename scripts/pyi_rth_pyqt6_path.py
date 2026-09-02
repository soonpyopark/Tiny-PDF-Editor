"""Put bundled Qt6 / VC / ICU dirs on the Windows DLL search path before QtCore loads."""

from pdf_editor.qt_runtime import prepare_qt_dll_paths

prepare_qt_dll_paths()
