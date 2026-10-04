# 求解镜像的 pip 固定版本

目标：给出一组完整的固定版本(连同全部依赖)，供 `provision.sh` 用 `pip3 install --no-deps` 装进镜像系统 Python 的 `/usr/local/lib/python3.10/dist-packages`。镜像的 Python 是 3.10.12，在 Mac 上求解即可，不需要开 VM。

## 1 约束：镜像自带的包

1. 拿到镜像的 `pip list --format=freeze`：现有镜像的 manifest 里 `## pip` 一节就是。
2. 只保留**系统自带**的包，去掉我们自己装的那些(它们在 `requirements.txt` 里)，再去掉 Ubuntu 特有、PyPI 上没有的包：`python-apt`、`command-not-found`、`ubuntu-*`、`systemd-python`、`*+dfsg` 等。
3. 加一行 `cffi==1.15.0`，这是镜像里 `python3-cffi-backend` 的版本，系统的 cryptography 3.4.8 要用它。
4. 去掉 cp310 下没有 wheel 的旧版本，比如 PyYAML 5.4.1。否则求解器会因为"装不了这个版本"而报冲突。

## 2 求解

```bash
pip install --dry-run --ignore-installed --report report.json --target /tmp/t \
  --python-version 3.10 --implementation cp --abi cp310 \
  --platform manylinux_2_35_x86_64 --platform manylinux_2_34_x86_64 --platform manylinux_2_28_x86_64 \
  --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --platform linux_x86_64 \
  --only-binary=:all: -c constraints.txt -r top.txt
```

`top.txt` 只列顶层包，依赖由求解器补齐。从 `report.json` 的 `install` 里取 `name==version`，去掉和约束完全相同的那些，剩下的就是要写进 `requirements.txt` 的。

## 3 常见冲突与处理

| 报错 | 处理 |
|---|---|
| `Could not find a version … (from versions: none)` | 这个包只有源码包。纯 Python 的话从 `top.txt` 拿掉，把它的依赖手动加进 `top.txt`，最后单独固定版本，写在 `requirements.txt` 末尾(如 ezodf、odfpy) |
| `X depends on Y>=…`，而 Y 是系统包 | 判断能不能在 `/usr/local` 里换一个较新的 Y：只影响科学计算的可以换(scipy 1.8 → 1.15)；系统工具也在用的不要换(cryptography、PyYAML、cffi)，改为固定 X 的旧版本，或者不装 X |
| 旧版本依赖的包没有 wheel | 评估影响的题数；很少的话不装，在 `RL_VM_ENVIRONMENT.md` §3.3 写明原因(如 pyhanko，1 道题) |

## 4 查结果

- 哪些包会覆盖系统的 apt 版本：拿新 manifest 的 pip 列表对照 `dpkg -l 'python3-*'`。
- 构建完后 `provision.sh` 末尾的 import 检查是第一道关；普查的 probe 是第二道关。
