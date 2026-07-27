# DSMaps Live Tracker

`드래곤소드: 어웨이크닝`의 현재 캐릭터 위치를 읽기 전용으로 확인해 [DSMaps](https://dsmaps.com/) 지도에 표시하는 Windows용 보조 프로그램입니다.

> 비공식 팬 프로젝트이며 하운드13과 제휴·승인 관계가 없습니다. 게임 관련 저작물과 상표의 권리는 각 권리자에게 있습니다.

## 작동 방식

- Windows `ReadProcessMemory` API로 게임 프로세스의 위치 값만 읽습니다.
- 게임 메모리를 수정하지 않으며 DLL 주입, 키 입력, 자동 조작을 하지 않습니다.
- `http://127.0.0.1:8765/position`에 지도 표시용 미터 좌표만 제공합니다.
- 프로세스 ID, 포인터 주소와 원본 메모리 값은 로컬 API에 노출하지 않습니다.
- 허용된 DSMaps 웹 출처에서만 브라우저가 좌표 응답을 사용할 수 있습니다.

## 설치 및 사용

1. [Releases](https://github.com/ghbproject/DSMaps-Live-Tracker/releases/latest)에서 `DSMapsLiveTracker-windows-x64.zip`을 받습니다.
2. ZIP의 압축을 모두 풉니다.
3. 폴더 안의 `DSMapsLiveTracker.exe`를 실행합니다. EXE만 따로 옮기면 안 됩니다.
4. 게임에 캐릭터로 접속하고 [DSMaps](https://dsmaps.com/)의 `LIVE BETA` 버튼을 엽니다.
5. 사용 후 GUI의 `종료` 버튼이나 창 닫기를 누릅니다.

## 직접 실행

Python 3.13 이상이 필요합니다.

```powershell
python tracker_gui.pyw
```

## 빌드

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean DSMapsLiveTracker.spec
```

결과물은 `dist/DSMapsLiveTracker/`에 생성됩니다. GitHub Release 빌드는 `.github/workflows/release.yml`에서 동일한 절차로 수행됩니다.

## 주의사항

- Windows 전용입니다.
- 게임 또는 보안 프로그램 업데이트로 메모리 구조가 바뀌면 작동하지 않을 수 있습니다.
- 서명되지 않은 신규 실행 파일은 Windows나 브라우저가 경고할 수 있습니다.
- 게임 운영정책 변경, 계정 제재 또는 데이터 손실 등 사용 중 발생한 결과에 대한 책임은 사용자에게 있습니다.

보안 문제는 공개 이슈 대신 [SECURITY.md](SECURITY.md)의 안내에 따라 제보해 주세요.

## 라이선스

[Apache License 2.0](LICENSE)
