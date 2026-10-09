#include <windows.h>
#include <cstdio>
int wmain(int argc,wchar_t**argv){
    if(argc!=3 || (wcscmp(argv[1],L"install") && wcscmp(argv[1],L"remove")))return 2;
    HKEY machine=nullptr;
    // Read the Classes root; DllRegisterServer creates only its own child keys.
    LONG err=RegOpenKeyExW(HKEY_LOCAL_MACHINE,L"Software\\Classes",0,KEY_READ,&machine);
    if(err){wprintf(L"Opening system camera registry failed: %ld\n",err);return 3;}
    err=RegOverridePredefKey(HKEY_CLASSES_ROOT,machine);
    if(err){RegCloseKey(machine);return 4;}
    HMODULE dll=LoadLibraryExW(argv[2],nullptr,LOAD_WITH_ALTERED_SEARCH_PATH);
    HRESULT hr=HRESULT_FROM_WIN32(GetLastError());
    if(dll){
        auto proc=reinterpret_cast<HRESULT(WINAPI*)()>(GetProcAddress(dll,!wcscmp(argv[1],L"install")?"DllRegisterServer":"DllUnregisterServer"));
        hr=proc?proc():E_NOINTERFACE;
        FreeLibrary(dll);
    }
    RegOverridePredefKey(HKEY_CLASSES_ROOT,nullptr);
    RegCloseKey(machine);
    wprintf(L"Camera registration result: 0x%08lX\n",(unsigned long)hr);
    return FAILED(hr)?5:0;
}
