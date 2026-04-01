"""
Chisel Toolchain Helpers

Shared utilities for locating Chisel JARs, downloading dependencies,
compiling Scala, emitting FIRRTL, and converting to Verilog via firtool.

Used by both RV32I and RV64I pipeline generators.
"""

import os
import shutil
import subprocess
from pathlib import Path


def find_jars():
    """Locate Chisel dependency JARs.

    Searches, in order:
      1. CHISEL_JARS_DIR environment variable
      2. /tmp/chisel_deps  (development fallback)
      3. ~/.cache/isacomp/chisel_deps
    Returns path to directory or None.
    """
    candidates = [
        os.environ.get('CHISEL_JARS_DIR'),
        '/tmp/chisel_deps',
        str(Path.home() / '.cache' / 'isacomp' / 'chisel_deps'),
    ]
    for c in candidates:
        if c and Path(c).is_dir():
            jars = list(Path(c).glob('*.jar'))
            if jars:
                return Path(c)
    return None


def download_jars(target_dir):
    """Download Chisel 6 dependency JARs from Maven Central using curl."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    curl_path = shutil.which('curl')
    if not curl_path:
        raise RuntimeError("curl not found in PATH; cannot download Chisel JARs")

    MAVEN = "https://repo1.maven.org/maven2"
    # Complete set of JARs needed for Chisel 6.6.0 + Scala 2.13.14
    jars = [
        ("org/scala-lang", "scala-library", "2.13.14"),
        ("org/scala-lang", "scala-reflect", "2.13.14"),
        ("org/scala-lang", "scala-compiler", "2.13.14"),
        ("org/chipsalliance", "chisel_2.13", "6.6.0"),
        ("org/chipsalliance", "chisel-plugin_2.13.14", "6.6.0"),
        ("com/github/scopt", "scopt_2.13", "4.1.0"),
        ("net/jcazevedo", "moultingyaml_2.13", "0.4.2"),
        ("org/json4s", "json4s-native_2.13", "4.0.6"),
        ("org/json4s", "json4s-core_2.13", "4.0.6"),
        ("org/json4s", "json4s-ast_2.13", "4.0.6"),
        ("org/json4s", "json4s-scalap_2.13", "4.0.6"),
        ("org/apache/commons", "commons-text", "1.10.0"),
        ("org/apache/commons", "commons-lang3", "3.12.0"),
        ("io/github/alexarchambault", "data-class_2.13", "0.2.6"),
        ("com/lihaoyi", "os-lib_2.13", "0.9.1"),
        ("com/lihaoyi", "geny_2.13", "1.0.0"),
        ("org/scala-lang/modules", "scala-parallel-collections_2.13", "1.0.4"),
        ("com/lihaoyi", "upickle_2.13", "3.1.0"),
        ("com/lihaoyi", "upickle-core_2.13", "3.1.0"),
        ("com/lihaoyi", "upickle-implicits_2.13", "3.1.0"),
        ("com/lihaoyi", "ujson_2.13", "3.1.0"),
        ("com/lihaoyi", "upack_2.13", "3.1.0"),
        ("com/lihaoyi", "sourcecode_2.13", "0.3.1"),
        ("org/scala-lang/modules", "scala-collection-compat_2.13", "2.11.0"),
        ("org/chipsalliance", "firtool-resolver_2.13", "1.3.0"),
        ("com/outr", "scribe_2.13", "3.13.0"),
        ("com/outr", "moduload_2.13", "1.1.7"),
        ("com/outr", "perfolation_2.13", "1.2.9"),
        ("org/yaml", "snakeyaml", "2.0"),
        ("com/thoughtworks/paranamer", "paranamer", "2.8"),
    ]

    downloaded = 0
    for group_path, artifact, version in jars:
        jar_file = target / f"{artifact}-{version}.jar"
        if jar_file.exists():
            continue
        url = f"{MAVEN}/{group_path}/{artifact}/{version}/{artifact}-{version}.jar"
        try:
            result = subprocess.run(
                [curl_path, "-fL", "--max-time", "30", url, "-o", str(jar_file)],
                capture_output=True, timeout=45
            )
            if result.returncode != 0:
                # Remove partial file on failure
                jar_file.unlink(missing_ok=True)
                print(f"    Warning: failed to download {artifact}-{version}.jar")
        except Exception:
            # Remove partial file on failure
            jar_file.unlink(missing_ok=True)
            print(f"    Warning: failed to download {artifact}-{version}.jar")
        else:
            if result.returncode == 0:
                downloaded += 1

    if downloaded > 0:
        print(f"  Downloaded {downloaded} JAR(s) to {target}")
    return target


def compile_scala(scala_file, class_name, jar_dir, output_classes_dir):
    """Compile a Scala file with Chisel plugin using scalac (no sbt needed)."""
    jar_dir = Path(jar_dir)
    output_classes_dir = Path(output_classes_dir)
    output_classes_dir.mkdir(parents=True, exist_ok=True)

    jars = list(jar_dir.glob('*.jar'))
    cp = os.pathsep.join(str(j) for j in jars)
    plugin_jar = jar_dir / 'chisel-plugin_2.13.14-6.6.0.jar'

    cmd = [
        'java', '-cp', cp, 'scala.tools.nsc.Main',
        f'-Xplugin:{plugin_jar}',
        '-classpath', cp,
        '-d', str(output_classes_dir),
        str(scala_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"scalac compilation failed:\n{result.stderr}")
    return True


def emit_firrtl(class_name, jar_dir, classes_dir, firrtl_dir):
    """Run the compiled Chisel main to emit FIRRTL."""
    jar_dir = Path(jar_dir)
    firrtl_dir = Path(firrtl_dir)
    firrtl_dir.mkdir(parents=True, exist_ok=True)

    jars = list(jar_dir.glob('*.jar'))
    cp = str(classes_dir) + os.pathsep + os.pathsep.join(str(j) for j in jars)
    main_class = f"{class_name}Main"

    result = subprocess.run(
        ['java', '-cp', cp, main_class, str(firrtl_dir)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"FIRRTL emission failed:\n{result.stderr}")

    firrtl_file = firrtl_dir / f"{class_name}.fir"
    if not firrtl_file.exists():
        raise RuntimeError(f"FIRRTL file not generated: {firrtl_file}")
    print(f"  {result.stdout.strip()}")
    return firrtl_file


def firrtl_to_verilog(firrtl_file, verilog_file):
    """Convert FIRRTL to Verilog using firtool."""
    firtool_path = shutil.which('firtool')
    if not firtool_path:
        raise RuntimeError("firtool not found in PATH (install from CIRCT releases)")

    result = subprocess.run(
        [firtool_path, str(firrtl_file), '--verilog', '-o', str(verilog_file),
         '--lowering-options=disallowLocalVariables'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"firtool conversion failed:\n{result.stderr}")
    return verilog_file
