

NAME = RawMouse

FILES = $(shell git ls-files)

default: ../$(NAME).zip

../$(NAME).zip: $(FILES)
	cd ..; zip -u $(NAME).zip $(addprefix $(NAME)/,$(FILES)) -x $(NAME)/Makefile || true
