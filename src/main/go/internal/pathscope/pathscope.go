// Package pathscope validates repository-relative Go source paths.
package pathscope

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

const MaxPathBytes = 4096

var (
	ErrInvalidPath  = errors.New("invalid repository-relative Go file path")
	ErrFileTooLarge = errors.New("go file exceeds the configured size limit")
)

// Resolve returns the resolved regular Go file beneath root.
func Resolve(root string, relative string, maxBytes int64) (string, error) {
	if relative == "" || len([]byte(relative)) > MaxPathBytes {
		return "", ErrInvalidPath
	}
	if strings.ContainsRune(relative, '\x00') || filepath.IsAbs(relative) {
		return "", ErrInvalidPath
	}
	cleaned := filepath.Clean(filepath.FromSlash(relative))
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, ".."+string(filepath.Separator)) {
		return "", ErrInvalidPath
	}
	if filepath.Ext(cleaned) != ".go" {
		return "", ErrInvalidPath
	}

	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", ErrInvalidPath
	}
	resolvedCandidate, err := filepath.EvalSymlinks(filepath.Join(resolvedRoot, cleaned))
	if err != nil {
		return "", ErrInvalidPath
	}
	underRoot, err := filepath.Rel(resolvedRoot, resolvedCandidate)
	if err != nil || underRoot == ".." || strings.HasPrefix(underRoot, ".."+string(filepath.Separator)) {
		return "", ErrInvalidPath
	}
	info, err := os.Stat(resolvedCandidate)
	if err != nil || !info.Mode().IsRegular() {
		return "", ErrInvalidPath
	}
	if info.Size() > maxBytes {
		return "", ErrFileTooLarge
	}
	return resolvedCandidate, nil
}
