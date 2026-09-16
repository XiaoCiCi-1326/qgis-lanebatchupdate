# -*- coding: utf-8 -*-
"""
Script to convert UTF-8 encoded Chinese bytes in regex patterns to Unicode escape sequences.
"""
import re
from pathlib import Path

TARGET_FILE = r"E:\刷转向与限速\lanebatchupdate\lane_fix_excel.py"

# All replacements: longer patterns first to avoid partial replacements
# Format: (bytes_to_find, replacement_string)
REPLACEMENTS = [
    # 4-char sequences
    (b'\xe4\xb8\x8d\xe5\xba\x94\xe6\x8c\x82\xe6\x8e\xa5', r'\u4e0d\u5e94\u62c5\u63a5'),  # 不应挂接
    (b'\xe7\xbc\xba\xe5\xa4\xb1\xe4\xba\x86', r'\u7f3a\u5931\u4e86'),  # 缺失了
    (b'\xe5\x9d\x87\xe6\x9c\xaa\xe8\xa2\xab', r'\u5747\u672a\u88ab'),  # 均未被
    (b'\xe5\x85\xb3\xe8\x81\x94\xe7\x9a\x84', r'\u5173\u8054\u7684'),  # 关联的
    (b'\xe5\x5d\x87\xe6\x9c\xaa', r'\u5747\u672a'),  # 均未
    # 3-char sequences (Chinese chars are 3 bytes in UTF-8)
    (b'\xe5\xba\x94\xe6\x8c\x82\xe6\x8e\xa5', r'\u5e94\u62c5\u63a5'),  # 应挂接
    (b'\xe4\xb8\x8d\xe5\xba\x94', r'\u4e0d\u5e94'),  # 不应
    (b'\xe4\xb8\x8d\xe5\xba\x94\xe6\x8c\x82', r'\u4e0d\u5e94\u62c5'),  # 不应挂
    (b'\xe5\xa4\x9a\xe4\xbd\x99', r'\u591a\u4f59'),  # 多余
    (b'\xe4\xba\x92\xe4\xb8\xba', r'\u4e92\u4e3a'),  # 互为
    (b'\xe5\x85\xb3\xe8\x81\x94', r'\u5173\u8054'),  # 关联
    (b'\xe9\x94\x99\xe8\xaf\xaf', r'\u9519\u8bef'),  # 错误
    (b'\xe7\xbc\xba\xe5\xa4\xb1', r'\u7f3a\u5931'),  # 缺失
    (b'\xe5\x8f\xb3\xe4\xbe\xa7', r'\u53f3\u4fa7'),  # 右侧
    (b'\xe5\xb7\xa6\xe4\xbe\xa7', r'\u5de6\u4fa7'),  # 左侧
    (b'\xe5\xb7\xa6\xe5\x8f\xb3', r'\u5de6\u53f3'),  # 左右
    (b'\xe4\xbd\x8d\xe9\x94\x99\xe8\xaf\xaf', r'\u4f4d\u9519\u8bef'),  # 位错误
    (b'\xe6\x9c\xaa\xe8\xa2\xab', r'\u672a\u88ab'),  # 未被
    (b'\xe5\xaf\xb9\xe6\x96\xb9', r'\u5bf9\u65b9'),  # 对方
    (b'\xe4\xb8\x80\xe4\xb8\xaa', r'\u4e00\u4e2a'),  # 一个
    # 2-char sequences (2 Chinese chars)
    (b'\xe4\xb8\x8e', r'\u4e0e'),  # 与
    (b'\xe5\x85\xb3', r'\u5173'),  # 关
    (b'\xe8\x81\x94', r'\u8054'),  # 联
    (b'\xe7\x9a\x84', r'\u7684'),  # 的
    (b'\xe4\xba\x92', r'\u4e92'),  # 互
    (b'\xe4\xb8\xba', r'\u4e3a'),  # 为
    (b'\xe5\xaf\xb9', r'\u5bf9'),  # 对
    (b'\xe6\x96\xb9', r'\u65b9'),  # 方
    (b'\xe5\x9d\x87', r'\u5747'),  # 均
    (b'\xe6\x9c\xaa', r'\u672a'),  # 未
    (b'\xe8\xbe\xb9', r'\u8fb9'),  # 边
    (b'\xe7\xba\xbf', r'\u7ebf'),  # 线
    (b'\xe6\x98\xaf', r'\u662f'),  # 是
    (b'\xe7\xa9\xba', r'\u7a7a'),  # 空
    (b'\xe4\xba\x86', r'\u4e86'),  # 了
    (b'\xe4\xb8\x80', r'\u4e00'),  # 一
    (b'\xe4\xb8\xad', r'\u4e2d'),  # 中
    (b'\xe4\xb8\x8b', r'\u4e0b'),  # 下
    (b'\xe5\x85\xa8', r'\u5168'),  # 全
    (b'\xe6\x88\x96', r'\u6216'),  # 或
    (b'\xe6\xaf\x8b', r'\u7686'),  # 皆
    (b'\xe8\xbe\x83', r'\u6bd4'),  # 比
    (b'\xe4\xb8\xaa', r'\u4e2a'),  # 个
    (b'\xe6\xbc\x8f', r'\u6f0f'),  # 漏
    (b'\xe7\xbc\xba', r'\u7f3a'),  # 缺
    (b'\xe8\xae\xb0', r'\u8bb0'),  # 记
    (b'\xe5\xbd\x95', r'\u5f55'),  # 录
    (b'\xe5\x88\x9b', r'\u521b'),  # 创
    (b'\xe9\x80\x89', r'\u9009'),  # 选
    (b'\xe4\xb8\x89', r'\u4e09'),  # 三
    # Punctuation (these are full-width chars, 3 bytes each in UTF-8)
    (b'\xe3\x80\x90', r'\u3010'),  # 【
    (b'\xe3\x80\x91', r'\u3011'),  # 】
    (b'\xe3\x80\x80', r'\u3000'),  # 全角空格
    # Full-width punctuation (these are 3 bytes in UTF-8: EF BC XX)
    (b'\xef\xbc\x9a', r'\uff1a'),  # ：
    (b'\xef\xbc\x8c', r'\uff0c'),  # ，
    (b'\xef\xbc\x9b', r'\uff1b'),  # ；
    (b'\xef\xbc\x81', r'\uff01'),  # ！
    (b'\xef\xbc\x9f', r'\uff1f'),  # ？
]

# Sort replacements by length (longest first) to avoid partial replacements
REPLACEMENTS.sort(key=lambda x: -len(x[0]))


def find_utf8_chinese_in_raw_strings(content: bytes) -> list:
    """Find any remaining UTF-8 Chinese sequences in raw string literals."""
    # 3-byte UTF-8 sequences start with E0-EF
    # 2-byte UTF-8 sequences start with C0-DF
    # Pattern: find raw string literals and check for Chinese bytes inside them
    
    # Find all r"..." and r'...' patterns
    pattern = rb'r(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\')'
    matches = list(re.finditer(pattern, content, re.DOTALL))
    
    remaining = []
    for m in matches:
        string_content = m.group(0)
        # Check for UTF-8 Chinese bytes (E4-E9 are common for Chinese)
        for i, b in enumerate(string_content):
            if b >= 0xE0 and b <= 0xEF:  # Start of 3-byte UTF-8 sequence
                # Check if it's a Chinese character
                remaining.append((m.start(), string_content[max(0,i-5):i+15]))
            elif b >= 0xC0 and b <= 0xDF:  # Start of 2-byte UTF-8 sequence
                remaining.append((m.start(), string_content[max(0,i-5):i+10]))
    
    return remaining


def process_file(filepath: str) -> dict:
    """Process the file and convert UTF-8 Chinese to Unicode escapes."""
    with open(filepath, 'rb') as f:
        original_content = f.read()
    
    content = original_content
    total_replacements = 0
    replacement_details = {}
    
    for old_bytes, new_str in REPLACEMENTS:
        count = content.count(old_bytes)
        if count > 0:
            content = content.replace(old_bytes, new_str.encode('utf-8'))
            total_replacements += count
            replacement_details[new_str] = count
    
    # Write the result back
    with open(filepath, 'wb') as f:
        f.write(content)
    
    return {
        'total_replacements': total_replacements,
        'replacement_details': replacement_details,
        'original_size': len(original_content),
        'new_size': len(content)
    }


def verify_file(filepath: str) -> dict:
    """Verify the file has no more UTF-8 Chinese sequences in raw strings."""
    with open(filepath, 'rb') as f:
        content = f.read()
    
    # Find all raw string literals (r"..." and r'...')
    # This regex matches raw strings - both single and triple quoted
    raw_string_pattern = rb'r(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
    raw_strings = re.findall(raw_string_pattern, content)
    
    # Check for remaining UTF-8 Chinese in raw strings only
    issues = []
    for raw_str in raw_strings:
        i = 0
        while i < len(raw_str):
            b = raw_str[i]
            
            # Check for 3-byte UTF-8 sequence (common for Chinese)
            if 0xE0 <= b <= 0xEF:
                if i + 2 < len(raw_str):
                    b1, b2 = raw_str[i+1], raw_str[i+2]
                    if (0x80 <= b1 <= 0xBF) and (0x80 <= b2 <= 0xBF):
                        # This is a valid 3-byte UTF-8 sequence
                        char_bytes = bytes([b, b1, b2])
                        try:
                            char_str = char_bytes.decode('utf-8')
                            if '\u4e00' <= char_str <= '\u9fff' or '\u3000' <= char_str <= '\u303f' or '\uff00' <= char_str <= '\uffef':
                                issues.append({
                                    'bytes': char_bytes.hex(),
                                    'char': char_str,
                                    'codepoint': hex(ord(char_str))
                                })
                        except:
                            pass
                        i += 3
                        continue
            i += 1
    
    # Check for common patterns that should have been replaced
    verification_patterns = {
        r'\u6f0f\u5f55': '漏录 (漏记录)',
        r'\u9519\u8bef': '错误',
        r'\u7f3a\u5931': '缺失',
        r'\u5173\u8054': '关联',
        r'\u62c5\u63a5': '挂接',
        r'\u5e94\u62c5': '应挂',
        r'\u4e0d\u5e94': '不应',
        r'\u591a\u4f59': '多余',
    }
    
    found_patterns = {}
    content_str = content.decode('utf-8', errors='replace')
    for pattern, description in verification_patterns.items():
        count = content_str.count(pattern)
        found_patterns[description] = count
    
    return {
        'remaining_issues': issues,
        'verification_patterns': found_patterns,
        'file_size': len(content)
    }


if __name__ == '__main__':
    print(f"Processing: {TARGET_FILE}")
    print("=" * 60)
    
    # Process the file
    result = process_file(TARGET_FILE)
    
    print(f"\n1. REPLACEMENT SUMMARY:")
    print(f"   Total replacements: {result['total_replacements']}")
    print(f"   Original size: {result['original_size']} bytes")
    print(f"   New size: {result['new_size']} bytes")
    
    if result['replacement_details']:
        print(f"\n   Breakdown by pattern:")
        for pattern, count in sorted(result['replacement_details'].items(), key=lambda x: -x[1]):
            print(f"   - {pattern}: {count} occurrences")
    
    # Verify the file
    print(f"\n2. VERIFICATION:")
    verify_result = verify_file(TARGET_FILE)
    
    if verify_result['remaining_issues']:
        print(f"   Remaining UTF-8 Chinese sequences found: {len(verify_result['remaining_issues'])}")
        for issue in verify_result['remaining_issues'][:10]:  # Show first 10
            print(f"   - Position {issue['position']}: {issue['bytes']} = '{issue['char']}' ({issue['codepoint']})")
    else:
        print(f"   ✓ No remaining UTF-8 Chinese sequences found!")
    
    print("\n3. KEY PATTERN VERIFICATION:")
    for desc, count in verify_result['verification_patterns'].items():
        status = "[OK]" if count > 0 else "[--]"
        print(f"   {status} {desc}: {count} occurrences")
    
    print("\n" + "=" * 60)
    print("Done!")
