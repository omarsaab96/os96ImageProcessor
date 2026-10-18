if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from optimizer.selftest import run
        raise SystemExit(run(sys.argv[2]))
    from optimizer.app import main
    main()
