package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
)

func verifyBaselineContents(directory, inventoryPath, expected string) error {
	body, err := os.ReadFile(inventoryPath)
	if err != nil {
		return err
	}
	var inventory struct {
		Schema int               `json:"schema"`
		Commit string            `json:"commit"`
		Files  map[string]string `json:"files"`
	}
	if json.Unmarshal(body, &inventory) != nil || inventory.Schema != 1 || inventory.Commit != expected || len(inventory.Files) == 0 {
		return errors.New("baseline_integrity_invalid")
	}
	directory, err = filepath.EvalSymlinks(directory)
	if err != nil {
		return err
	}
	hash := sha256.New()
	buffer := make([]byte, 64*1024)
	var sum [sha256.Size]byte
	var encoded [sha256.Size * 2]byte
	checked := 0
	err = filepath.WalkDir(directory, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		name, err := filepath.Rel(directory, path)
		if err != nil {
			return err
		}
		wanted, ok := inventory.Files[filepath.ToSlash(name)]
		if !ok || !entry.Type().IsRegular() || !hashPattern.MatchString(wanted) {
			return errors.New("baseline_integrity_mismatch")
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		hash.Reset()
		_, err = io.CopyBuffer(hash, struct{ io.Reader }{file}, buffer)
		closeErr := file.Close()
		if err != nil {
			return err
		}
		if closeErr != nil {
			return closeErr
		}
		hex.Encode(encoded[:], hash.Sum(sum[:0]))
		if string(encoded[:]) != wanted {
			return errors.New("baseline_integrity_mismatch")
		}
		checked++
		return nil
	})
	if err != nil {
		return err
	}
	if checked != len(inventory.Files) {
		return errors.New("baseline_integrity_mismatch")
	}
	return nil
}
